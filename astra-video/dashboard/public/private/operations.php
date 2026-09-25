<?php
declare(strict_types=1);

const LOCAL_ZONE = 'Asia/Colombo';

function next_slot(array $slots, ?DateTimeImmutable $after = null, string $zone = 'America/New_York'): string {
    $local = ($after ?? new DateTimeImmutable('now'))->setTimezone(new DateTimeZone($zone));
    sort($slots);
    for ($day = 0; $day < 3; $day++) {
        foreach ($slots as $slot) {
            [$hour, $minute] = array_map('intval', explode(':', $slot));
            $candidate = $local->modify("+$day day")->setTime($hour, $minute, 0);
            if ($candidate > $local) return $candidate->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i:s');
        }
    }
    throw new InvalidArgumentException('At least one daily time is required.');
}

function migrate_operations(PDO $pdo): void {
    foreach (explode(';', file_get_contents(__DIR__.'/operations-schema.sql')) as $sql) {
        if (trim($sql)) $pdo->exec($sql);
    }
    $pdo->exec('INSERT IGNORE INTO execution_gate(id,paused) VALUES (1,1)');
    foreach (['fetch'=>['11:15','17:15','20:15'], 'editor'=>[], 'uploader'=>['12:00','18:00','21:00']] as $name=>$slots) {
        $q=$pdo->prepare('INSERT IGNORE INTO agents(name,slots,next_run) VALUES (?,?,?)');
        $q->execute([$name,json_encode($slots),$slots ? next_slot($slots) : null]);
    }
}

function lock_gate(PDO $pdo): array {
    return $pdo->query('SELECT * FROM execution_gate WHERE id=1 FOR UPDATE')->fetch();
}

function insert_task(PDO $pdo, string $agent, int $channel, ?int $job, string $key, ?string $due=null): int {
    $q=$pdo->prepare('INSERT IGNORE INTO pipeline_tasks(agent,channel_id,job_id,request_key,scheduled_at) VALUES (?,?,?,?,?)');
    $q->execute([$agent,$channel,$job,$key,$due ?? gmdate('Y-m-d H:i:s')]);
    $q=$pdo->prepare('SELECT id FROM pipeline_tasks WHERE request_key=?'); $q->execute([$key]);
    return (int)$q->fetchColumn();
}

function queue_edits(PDO $pdo): int {
    $rows=$pdo->query("SELECT v.* FROM video_progress v JOIN jobs j ON j.id=v.job_id JOIN channels c ON c.id=v.channel_id WHERE c.enabled=1 AND v.edited_at IS NULL AND v.blocked_reason IS NULL AND j.status NOT IN ('skipped','failed','cancelled','needs_attention')")->fetchAll();
    foreach ($rows as $row) insert_task($pdo,'editor',(int)$row['channel_id'],(int)$row['job_id'],'editor:'.$row['job_id']);
    return count($rows);
}

function ready_video(PDO $pdo): array|false {
    return $pdo->query("SELECT v.* FROM video_progress v JOIN jobs j ON j.id=v.job_id JOIN channels c ON c.id=v.channel_id WHERE c.enabled=1 AND v.edited_at IS NOT NULL AND v.title_ready=1 AND v.published_at IS NULL AND v.blocked_reason IS NULL AND j.status='ready' AND NOT EXISTS (SELECT 1 FROM pipeline_tasks t WHERE t.job_id=v.job_id AND t.agent='uploader' AND t.state IN ('queued','running','needs_attention')) ORDER BY v.downloaded_at,v.job_id LIMIT 1 FOR UPDATE")->fetch();
}

function upload_pending(PDO $pdo): bool {
    return (bool)$pdo->query("SELECT id FROM pipeline_tasks WHERE agent='uploader' AND state IN ('queued','running','needs_attention') LIMIT 1")->fetchColumn();
}

// The caller holds the shared gate for the whole scheduling decision.
function tick_schedule(PDO $pdo): void {
    $gate=lock_gate($pdo);
    if ($gate['paused']) return;
    $agents=$pdo->query('SELECT * FROM agents WHERE enabled=1 FOR UPDATE')->fetchAll();
    foreach ($agents as $agent) {
        $name=$agent['name'];
        if ($name==='editor') { queue_edits($pdo); continue; }
        if (!$agent['next_run'] || $agent['next_run'] > gmdate('Y-m-d H:i:s')) continue;
        $slot=$agent['next_run'];
        if ($name==='fetch') {
            foreach ($pdo->query('SELECT id FROM channels WHERE enabled=1')->fetchAll() as $channel) {
                $q=$pdo->prepare("SELECT id FROM pipeline_tasks WHERE channel_id=? AND agent='fetch' AND state IN ('queued','running') LIMIT 1"); $q->execute([$channel['id']]);
                if (!$q->fetchColumn()) insert_task($pdo,'fetch',(int)$channel['id'],null,'fetch:'.$channel['id'].':'.$slot,$slot);
            }
        } else {
            $video=upload_pending($pdo)?false:ready_video($pdo);
            if ($video) insert_task($pdo,'uploader',(int)$video['channel_id'],(int)$video['job_id'],'uploader:'.$video['job_id'],$slot);
            else event($pdo,null,'scheduler','warning','Post slot skipped: no eligible video, or an earlier upload is still pending.');
        }
        // Coalesce missed slots rather than creating a burst after downtime.
        $q=$pdo->prepare('UPDATE agents SET next_run=? WHERE name=?');
        $q->execute([next_slot(json_decode($agent['slots'],true),null,$agent['schedule_timezone']),$name]);
    }
}

function claim_task(PDO $pdo, string $worker, array $capabilities, ?string $claimLease=null): ?array {
    $gate=lock_gate($pdo);
    if ($gate['paused'] || $gate['current_task']) return null;
    $q=$pdo->query("SELECT t.*,c.enabled channel_enabled FROM pipeline_tasks t JOIN agents a ON a.name=t.agent JOIN channels c ON c.id=t.channel_id WHERE t.state='queued' AND t.scheduled_at<=UTC_TIMESTAMP() AND a.enabled=1 ORDER BY t.scheduled_at,FIELD(t.agent,'editor','uploader','fetch'),t.id FOR UPDATE");
    foreach ($q->fetchAll() as $task) {
        if (!$task['channel_enabled'] || !in_array($task['agent'],$capabilities,true)) continue;
        if ($task['agent']==='uploader') {
            $posted=(int)$pdo->query("SELECT COUNT(*) FROM video_progress WHERE published_at >= DATE(DATE_ADD(UTC_TIMESTAMP(),INTERVAL 330 MINUTE))-INTERVAL 330 MINUTE")->fetchColumn();
            if ($posted>=3) continue;
            $check=$pdo->prepare("SELECT v.job_id FROM video_progress v JOIN jobs j ON j.id=v.job_id WHERE v.job_id=? AND v.edited_at IS NOT NULL AND v.title_ready=1 AND v.published_at IS NULL AND v.blocked_reason IS NULL AND j.status='ready' FOR UPDATE"); $check->execute([$task['job_id']]);
            if (!$check->fetchColumn()) {
                $update=$pdo->prepare("UPDATE pipeline_tasks SET state='blocked',reason='Upload blocked: this video is not eligible.',finished_at=UTC_TIMESTAMP() WHERE id=?"); $update->execute([$task['id']]);
                event($pdo,(int)$task['job_id'],'uploader','error','Upload blocked: video is skipped, unedited, already posted or needs attention.');
                continue;
            }
        }
        $lease=$claimLease ?? bin2hex(random_bytes(32));
        $update=$pdo->prepare("UPDATE pipeline_tasks SET state='running',started_at=UTC_TIMESTAMP(),heartbeat_at=UTC_TIMESTAMP(),worker_name=?,lease_hash=?,attempts=attempts+1,stop_requested=0 WHERE id=?");
        $update->execute([$worker,hash('sha256',$lease),$task['id']]);
        $update=$pdo->prepare('UPDATE execution_gate SET current_task=? WHERE id=1'); $update->execute([$task['id']]);
        $update=$pdo->prepare('UPDATE agents SET last_started=UTC_TIMESTAMP() WHERE name=?'); $update->execute([$task['agent']]);
        if ($task['job_id']) {
            $update=$pdo->prepare('UPDATE jobs SET status=?,stage=? WHERE id=?');
            $update->execute([$task['agent']==='editor'?'editing':'uploading',$task['agent'],$task['job_id']]);
        }
        event($pdo,$task['job_id']?(int)$task['job_id']:null,$task['agent'],'info','Task #'.$task['id'].' started; exclusive execution slot acquired.');
        $task['lease']=$lease;
        $task['state']='running';
        unset($task['lease_hash']);
        return $task;
    }
    return null;
}

function owned_task(PDO $pdo, string $worker, int $id, string $lease): array {
    $gate=lock_gate($pdo);
    $q=$pdo->prepare('SELECT * FROM pipeline_tasks WHERE id=? FOR UPDATE'); $q->execute([$id]); $task=$q->fetch();
    if (!$task || (int)$gate['current_task']!==$id || $task['state']!=='running' || $task['worker_name']!==$worker || !hash_equals((string)$task['lease_hash'],hash('sha256',$lease))) throw new InvalidArgumentException('The task lease is not valid.');
    return $task;
}

function complete_task(PDO $pdo, string $worker, array $body): void {
    $task=owned_task($pdo,$worker,(int)($body['id']??0),(string)($body['lease']??''));
    $state=(string)($body['state']??'');
    if (!in_array($state,['completed','failed','skipped','cancelled','needs_attention'],true)) throw new InvalidArgumentException('Invalid completion state.');
    $reason=mb_substr(trim((string)($body['reason']??'')),0,1000);
    if ($state!=='completed' && !$reason) throw new InvalidArgumentException('A reason is required.');
    $job=$task['job_id']?(int)$task['job_id']:null;
    if ($state==='completed' && $task['agent']==='fetch') {
        $videos=$body['videos']??[];
        if (!is_array($videos) || count($videos)>5) throw new InvalidArgumentException('A fetch can report at most five downloads.');
        foreach ($videos as $video) {
            $id=(string)($video['id']??'');
            if (!preg_match('/^[A-Za-z0-9_-]{11}$/',$id)) throw new InvalidArgumentException('A valid source video ID is required.');
            $q=$pdo->prepare('SELECT job_id FROM video_progress WHERE channel_id=? AND source_video_id=?');$q->execute([$task['channel_id'],$id]);
            $existing=$q->fetchColumn();
            $title=mb_substr((string)($video['title']??$id),0,255);
            if ($existing) {
                $q=$pdo->prepare("INSERT IGNORE INTO fetch_observations(task_id,source_video_id,title,result,job_id) VALUES (?,?,?,'duplicate',?)");$q->execute([$task['id'],$id,$title,$existing]);
                event($pdo,(int)$existing,'fetch','info','Duplicate skipped: '.$title.' ['.$id.']');
                continue;
            }
            if (empty($video['downloaded'])) {
                $skipReason=mb_substr(trim((string)($video['reason']??'')),0,1000);
                if (!$skipReason) throw new InvalidArgumentException('An undownloaded video must have a skip reason.');
                $q=$pdo->prepare("INSERT IGNORE INTO fetch_observations(task_id,source_video_id,title,result,reason) VALUES (?,?,?,'skipped',?)");$q->execute([$task['id'],$id,$title,$skipReason]);
                event($pdo,null,'fetch','warning','Video skipped: '.$title.' — '.$skipReason);
                continue;
            }
            $q=$pdo->prepare("INSERT INTO jobs(channel_id,status,stage,source_video_id,source_url,original_title,title) VALUES (?,'downloaded','editor',?,?,?,?)");
            $q->execute([$task['channel_id'],$id,'https://www.youtube.com/shorts/'.$id,$title,$title]); $new=(int)$pdo->lastInsertId();
            $q=$pdo->prepare('INSERT INTO video_progress(job_id,channel_id,source_video_id,downloaded_at) VALUES (?,?,?,UTC_TIMESTAMP())'); $q->execute([$new,$task['channel_id'],$id]);
            insert_task($pdo,'editor',(int)$task['channel_id'],$new,'editor:'.$new);
            $q=$pdo->prepare("INSERT IGNORE INTO fetch_observations(task_id,source_video_id,title,result,job_id) VALUES (?,?,?,'downloaded',?)");$q->execute([$task['id'],$id,$title,$new]);
            event($pdo,$new,'fetch','success','Downloaded and added to the editor queue.');
        }
    } elseif ($state==='completed' && $task['agent']==='editor') {
        if (empty($body['render_verified']) || !trim((string)($body['title']??''))) throw new InvalidArgumentException('A verified finished render and final title are required.');
        $q=$pdo->prepare('UPDATE video_progress SET edited_at=UTC_TIMESTAMP(),title_ready=1,blocked_reason=NULL WHERE job_id=?');$q->execute([$job]);
        $q=$pdo->prepare("UPDATE jobs SET status='ready',stage='uploader',progress=100,error=NULL,title=COALESCE(?,title) WHERE id=?");$q->execute([isset($body['title'])?mb_substr((string)$body['title'],0,255):null,$job]);
    } elseif ($state==='completed' && $task['agent']==='uploader') {
        $youtubeId=(string)($body['youtube_id']??'');
        if (empty($body['publication_confirmed']) || !preg_match('/^[A-Za-z0-9_-]{11}$/',$youtubeId)) throw new InvalidArgumentException('YouTube publication must be confirmed with a video ID.');
        $q=$pdo->prepare("UPDATE jobs SET status='published',progress=100,published_url=?,finished_at=UTC_TIMESTAMP(),error=NULL WHERE id=?");$q->execute(['https://www.youtube.com/watch?v='.$youtubeId,$job]);
        $q=$pdo->prepare('UPDATE video_progress SET published_at=UTC_TIMESTAMP() WHERE job_id=?');$q->execute([$job]);
    } elseif ($job) {
        // An uncertain upload must be reconciled, never retried blindly.
        if ($task['agent']==='uploader') $state='needs_attention';
        $q=$pdo->prepare('UPDATE jobs SET status=?,error=? WHERE id=?');$q->execute([$state,$reason,$job]);
        $q=$pdo->prepare('UPDATE video_progress SET blocked_reason=? WHERE job_id=?');$q->execute([$reason,$job]);
    }
    $q=$pdo->prepare('UPDATE pipeline_tasks SET state=?,reason=?,finished_at=UTC_TIMESTAMP(),progress=? WHERE id=?');$q->execute([$state,$reason?:null,$state==='completed'?100:0,$task['id']]);
    $pdo->exec('UPDATE execution_gate SET current_task=NULL WHERE id=1');
    $q=$pdo->prepare('UPDATE agents SET last_finished=UTC_TIMESTAMP() WHERE name=?');$q->execute([$task['agent']]);
    event($pdo,$job,$task['agent'],$state==='completed'?'success':($state==='skipped'?'warning':'error'),'Task #'.$task['id'].' '.$state.($reason?': '.$reason:'.'));
}

function operations_snapshot(PDO $pdo): array {
    $gate=$pdo->query('SELECT * FROM execution_gate WHERE id=1')->fetch();
    $agents=$pdo->query('SELECT * FROM agents ORDER BY FIELD(name,\'fetch\',\'editor\',\'uploader\')')->fetchAll();
    $active=null;
    if ($gate['current_task']) {
        $q=$pdo->prepare('SELECT id,agent,state,started_at,heartbeat_at,stop_requested,progress,TIMESTAMPDIFF(SECOND,heartbeat_at,UTC_TIMESTAMP()) heartbeat_age FROM pipeline_tasks WHERE id=?');$q->execute([$gate['current_task']]);$active=$q->fetch();
    }
    $workers=$pdo->query('SELECT name,kind,last_seen,TIMESTAMPDIFF(SECOND,last_seen,UTC_TIMESTAMP()) age_seconds FROM workers')->fetchAll();
    $online=count(array_filter($workers,fn($w)=>$w['age_seconds']!==null && (int)$w['age_seconds']<90))>0;
    foreach ($agents as &$agent) {
        $agent['slots']=json_decode($agent['slots'],true);
        $agent['display_slots']=[];
        foreach ($agent['slots'] as $slot) {
            $target=new DateTimeImmutable('today '.$slot,new DateTimeZone($agent['schedule_timezone']));
            $agent['display_slots'][]=$target->setTimezone(new DateTimeZone(LOCAL_ZONE))->format('H:i');
        }
        sort($agent['display_slots']);
        $agentOnline=count(array_filter($workers,fn($w)=>$w['age_seconds']!==null && (int)$w['age_seconds']<90 && in_array($agent['name'],explode(',',$w['kind']),true)))>0;
        $q=$pdo->prepare("SELECT COUNT(*) FROM pipeline_tasks WHERE agent=? AND state='queued'");$q->execute([$agent['name']]);$agent['queued']=(int)$q->fetchColumn();
        $agent['state']=$gate['paused']||!$agent['enabled']?'paused':($agentOnline?'waiting':'offline');
        if ($active && $active['agent']===$agent['name']) $agent['state']=$active['heartbeat_age']>120?'stalled':($active['stop_requested']?'stopping':'running');
        $agent['progress']=$active && $active['agent']===$agent['name']?(int)$active['progress']:0;
    }
    unset($agent);
    $ready=(int)$pdo->query("SELECT COUNT(*) FROM video_progress v JOIN jobs j ON j.id=v.job_id WHERE v.edited_at IS NOT NULL AND v.title_ready=1 AND v.published_at IS NULL AND v.blocked_reason IS NULL AND j.status='ready'")->fetchColumn();
    $blocked=(int)$pdo->query("SELECT COUNT(*) FROM pipeline_tasks WHERE state IN ('failed','blocked','skipped','needs_attention') OR (state='running' AND heartbeat_at<UTC_TIMESTAMP()-INTERVAL 120 SECOND)")->fetchColumn();
    $tasks=$pdo->query('SELECT t.id,t.agent,t.channel_id,t.job_id,t.state,t.scheduled_at,t.started_at,t.finished_at,t.stop_requested,t.progress,t.reason,t.attempts,c.name channel_name,j.title,j.published_url FROM pipeline_tasks t JOIN channels c ON c.id=t.channel_id LEFT JOIN jobs j ON j.id=t.job_id ORDER BY t.id DESC LIMIT 200')->fetchAll();
    $published=$pdo->query("SELECT j.id,j.title,j.published_url,j.finished_at,c.name channel_name FROM jobs j JOIN channels c ON c.id=j.channel_id WHERE j.status='published' ORDER BY j.finished_at DESC LIMIT 12")->fetchAll();
    $scan=$pdo->query('SELECT f.*,c.name channel_name FROM fetch_observations f JOIN pipeline_tasks t ON t.id=f.task_id JOIN channels c ON c.id=t.channel_id ORDER BY f.task_id DESC,f.checked_at DESC LIMIT 5')->fetchAll();
    return ['server_time'=>gmdate('c'),'timezone'=>LOCAL_ZONE,'paused'=>(bool)$gate['paused'],'online'=>$online,'agents'=>$agents,'active'=>$active,'ready'=>$ready,'blocked'=>$blocked,'tasks'=>$tasks,'published'=>$published,'latest_scan'=>$scan,'workers'=>$workers,'fetch_limit'=>5,'schedule_note'=>'US Eastern slots adjust for daylight saving. Displayed in Sri Lanka time.'];
}

function handle_operations(PDO $pdo, string $action, array $body): array {
    if ($action==='operations_migrate') { migrate_operations($pdo); return ['ok'=>true]; }
    $pdo->beginTransaction();
    $gate=lock_gate($pdo);
    if ($action==='pipeline_control') {
        $start=($body['command']??'')==='start';
        if (!in_array($body['command']??'',['start','stop'],true)) throw new InvalidArgumentException('Choose start or stop.');
        $q=$pdo->prepare('UPDATE execution_gate SET paused=? WHERE id=1');$q->execute([$start?0:1]);
        if (!$start && $gate['current_task']) {$q=$pdo->prepare('UPDATE pipeline_tasks SET stop_requested=1 WHERE id=?');$q->execute([$gate['current_task']]);}
        event($pdo,null,'scheduler','info',$start?'Pipeline enabled. Waiting for a connected worker.':'Pipeline paused. Active work must stop before the execution slot is released.');
    } elseif ($action==='agent_control') {
        $agent=(string)($body['agent']??'');
        if (!in_array($agent,['fetch','editor','uploader'],true) || !in_array($body['command']??'',['start','stop'],true)) throw new InvalidArgumentException('Invalid agent command.');
        $start=$body['command']==='start';$q=$pdo->prepare('UPDATE agents SET enabled=? WHERE name=?');$q->execute([$start?1:0,$agent]);
        if (!$start) {$q=$pdo->prepare("UPDATE pipeline_tasks SET stop_requested=1 WHERE agent=? AND state='running'");$q->execute([$agent]);}
        event($pdo,null,$agent,'info',$start?'Agent enabled.':'Agent paused; no further tasks will start.');
    } elseif ($action==='agent_schedule') {
        $agent=(string)($body['agent']??''); $slots=$body['slots']??[];
        if (!in_array($agent,['fetch','uploader'],true) || !is_array($slots) || count($slots)<1 || count($slots)>12) throw new InvalidArgumentException('Choose between 1 and 12 daily times.');
        foreach ($slots as $slot) if (!is_string($slot)||!preg_match('/^(?:[01]\d|2[0-3]):[0-5]\d$/',$slot)) throw new InvalidArgumentException('Use 24-hour times such as 08:00.');
        $slots=array_values(array_unique($slots));sort($slots);
        if ($agent==='fetch' && count($slots)!==3) throw new InvalidArgumentException('Set exactly three daily fetch times.');
        $zone=(string)($body['timezone']??LOCAL_ZONE);
        if (!in_array($zone,[LOCAL_ZONE,'America/New_York'],true)) throw new InvalidArgumentException('Unsupported schedule timezone.');
        if ($agent==='uploader' && count($slots)!==3) throw new InvalidArgumentException('Set exactly three daily post times.');
        $q=$pdo->prepare('UPDATE agents SET slots=?,next_run=?,schedule_timezone=? WHERE name=?');$q->execute([json_encode($slots),next_slot($slots,null,$zone),$zone,$agent]);
        event($pdo,null,'scheduler','info',ucfirst($agent).' times saved: '.implode(', ',$slots));
    } elseif ($action==='agent_run') {
        $agent=$body['agent']??'';
        if ($agent==='fetch') {
            foreach ($pdo->query('SELECT id FROM channels WHERE enabled=1')->fetchAll() as $channel) {
                $q=$pdo->prepare("SELECT id FROM pipeline_tasks WHERE channel_id=? AND agent='fetch' AND state IN ('queued','running')");$q->execute([$channel['id']]);
                if (!$q->fetchColumn()) insert_task($pdo,'fetch',(int)$channel['id'],null,'manual:'.bin2hex(random_bytes(12)));
            }
        } elseif ($agent==='editor') queue_edits($pdo);
        elseif ($agent==='uploader') {
            $immediate=($body['immediate']??false)===true;
            if ($immediate) {
                if ($gate['paused']) throw new InvalidArgumentException('Start the pipeline before uploading now.');
                if (!(int)$pdo->query("SELECT enabled FROM agents WHERE name='uploader'")->fetchColumn()) throw new InvalidArgumentException('Enable the upload agent first.');
                $posted=(int)$pdo->query("SELECT COUNT(*) FROM video_progress WHERE published_at >= DATE(DATE_ADD(UTC_TIMESTAMP(),INTERVAL 330 MINUTE))-INTERVAL 330 MINUTE")->fetchColumn();
                if ($posted>=3) throw new InvalidArgumentException('Today’s limit of three posts has been reached (Sri Lanka time).');
            }
            if (upload_pending($pdo)) throw new InvalidArgumentException('An upload is already queued or needs attention. Resolve it before queuing another.');
            $video=ready_video($pdo);
            if (!$video) throw new InvalidArgumentException('Nothing can be posted. A successfully edited, unblocked video is required.');
            $due=$immediate?null:$pdo->query("SELECT next_run FROM agents WHERE name='uploader'")->fetchColumn();
            insert_task($pdo,'uploader',(int)$video['channel_id'],(int)$video['job_id'],'uploader:'.$video['job_id'],$due?:null);
            if ($immediate) event($pdo,(int)$video['job_id'],'uploader','info','Upload now queued. Waiting for the worker and exclusive execution slot.');
        } else throw new InvalidArgumentException('Unknown agent.');
        event($pdo,null,$agent,'info','Manual queue request saved. Paused agents will wait until started.');
    } elseif ($action==='task_skip' || $action==='task_retry') {
        $q=$pdo->prepare('SELECT * FROM pipeline_tasks WHERE id=? FOR UPDATE');$q->execute([(int)($body['id']??0)]);$task=$q->fetch();
        if (!$task) throw new InvalidArgumentException('Task not found.');
        if ($action==='task_skip') {
            if ($task['state']!=='queued') throw new InvalidArgumentException('Only queued work can be skipped. Stop running work first.');
            $reason=mb_substr(trim((string)($body['reason']??'')),0,1000);
            if (!$reason) throw new InvalidArgumentException('Add a reason for skipping this task.');
            $q=$pdo->prepare("UPDATE pipeline_tasks SET state='skipped',reason=?,finished_at=UTC_TIMESTAMP() WHERE id=?");$q->execute([$reason,$task['id']]);
            if ($task['job_id']) {
                $q=$pdo->prepare("UPDATE jobs SET status='skipped',error=? WHERE id=?");$q->execute([$reason,$task['job_id']]);
                $q=$pdo->prepare('UPDATE video_progress SET blocked_reason=? WHERE job_id=?');$q->execute([$reason,$task['job_id']]);
            }
            event($pdo,$task['job_id']?(int)$task['job_id']:null,$task['agent'],'warning','Task #'.$task['id'].' skipped: '.$reason);
        } else {
            if (!in_array($task['state'],['failed','skipped','cancelled'],true) || $task['agent']==='uploader') throw new InvalidArgumentException('This task cannot be retried automatically. Uploads need publication reconciliation.');
            $q=$pdo->prepare("UPDATE pipeline_tasks SET state='queued',reason=NULL,finished_at=NULL,started_at=NULL,scheduled_at=UTC_TIMESTAMP(),progress=0 WHERE id=?");$q->execute([$task['id']]);
            if ($task['job_id']) {
                $q=$pdo->prepare("UPDATE jobs SET status='downloaded',error=NULL WHERE id=?");$q->execute([$task['job_id']]);
                $q=$pdo->prepare('UPDATE video_progress SET blocked_reason=NULL WHERE job_id=?');$q->execute([$task['job_id']]);
            }
            event($pdo,$task['job_id']?(int)$task['job_id']:null,$task['agent'],'info','Task #'.$task['id'].' queued for retry.');
        }
    } else throw new InvalidArgumentException('Unknown operation.');
    $pdo->commit(); return ['ok'=>true];
}
