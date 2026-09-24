<?php
declare(strict_types=1);

// All fixtures and events are rolled back before this check returns.
function run_queue_checks(PDO $pdo): array {
    $checks=[];
    $check=function(bool $ok,string $name) use (&$checks): void {
        if (!$ok) throw new RuntimeException('Queue check failed: '.$name);
        $checks[]=$name;
    };
    $pdo->beginTransaction();
    try {
        $gate=lock_gate($pdo);
        if ($gate['current_task']) throw new InvalidArgumentException('Wait until the active task finishes before running diagnostics.');
        $pdo->exec('UPDATE execution_gate SET paused=0 WHERE id=1');
        $pdo->exec('UPDATE channels SET enabled=0');
        $pdo->exec('UPDATE agents SET enabled=1');
        $q=$pdo->prepare('INSERT INTO channels(name,handle) VALUES (?,?)');$q->execute(['Queue diagnostic','@check_'.bin2hex(random_bytes(6))]);$channel=(int)$pdo->lastInsertId();
        $key='check:'.bin2hex(random_bytes(12));
        $id=insert_task($pdo,'fetch',$channel,null,$key);
        $check(insert_task($pdo,'fetch',$channel,null,$key)===$id,'Repeated schedule slots are deduplicated');
        $task=claim_task($pdo,'diagnostic',['fetch','editor','uploader']);
        $check($task && (int)$task['id']===$id,'A queued task acquires the shared slot');
        $check(claim_task($pdo,'other-worker',['fetch','editor','uploader'])===null,'Concurrent work cannot acquire a second slot');
        $pdo->exec('UPDATE pipeline_tasks SET heartbeat_at=UTC_TIMESTAMP()-INTERVAL 10 MINUTE WHERE id='.$id);
        $check(claim_task($pdo,'other-worker',['fetch','editor','uploader'])===null,'A stale lease remains locked until acknowledged');
        $rejected=false;
        try { owned_task($pdo,'diagnostic',$id,'bad-token'); } catch (InvalidArgumentException) { $rejected=true; }
        $check($rejected,'Stale completion tokens are rejected');
        $video=['id'=>'abcdefghijk','title'=>'Queue diagnostic','downloaded'=>true];
        complete_task($pdo,'diagnostic',['id'=>$id,'lease'=>$task['lease'],'state'=>'completed','videos'=>[$video,$video]]);
        $q=$pdo->prepare('SELECT COUNT(*) FROM video_progress WHERE channel_id=?');$q->execute([$channel]);
        $check((int)$q->fetchColumn()===1,'Overlapping latest-five results create one video');
        $edit=claim_task($pdo,'diagnostic',['editor']);
        $check($edit && $edit['agent']==='editor','Every new download enters the editor queue');
        complete_task($pdo,'diagnostic',['id'=>$edit['id'],'lease'=>$edit['lease'],'state'=>'completed','render_verified'=>true,'title'=>'Final diagnostic title']);
        $q=$pdo->prepare('SELECT title_ready,edited_at FROM video_progress WHERE job_id=?');$q->execute([$edit['job_id']]);$progress=$q->fetch();
        $check((bool)$progress['title_ready'] && (bool)$progress['edited_at'],'Title and editor completion are saved separately');
        $uploadId=insert_task($pdo,'uploader',$channel,(int)$edit['job_id'],'uploader:'.$edit['job_id']);
        $q=$pdo->prepare("UPDATE video_progress SET blocked_reason='Skipped by operator' WHERE job_id=?");$q->execute([$edit['job_id']]);
        $check(claim_task($pdo,'diagnostic',['uploader'])===null,'Skipped videos cannot be uploaded');
        $q=$pdo->prepare('SELECT state FROM pipeline_tasks WHERE id=?');$q->execute([$uploadId]);$check($q->fetchColumn()==='blocked','Ineligible upload is held with a reason');
        $q=$pdo->prepare('UPDATE video_progress SET blocked_reason=NULL WHERE job_id=?');$q->execute([$edit['job_id']]);
        $q=$pdo->prepare("UPDATE pipeline_tasks SET state='queued' WHERE id=?");$q->execute([$uploadId]);
        $upload=claim_task($pdo,'diagnostic',['uploader']);
        $rejected=false;
        try { complete_task($pdo,'diagnostic',['id'=>$uploadId,'lease'=>$upload['lease'],'state'=>'completed']); } catch (InvalidArgumentException) { $rejected=true; }
        $check($rejected,'Publication needs an explicit YouTube confirmation');
        complete_task($pdo,'diagnostic',['id'=>$uploadId,'lease'=>$upload['lease'],'state'=>'completed','youtube_id'=>'zyxwvutsrqp','publication_confirmed'=>true]);
        $q=$pdo->prepare('SELECT published_at FROM video_progress WHERE job_id=?');$q->execute([$edit['job_id']]);$check((bool)$q->fetchColumn(),'Confirmed publication records the actual time');
        $summer=next_slot(['12:00'],new DateTimeImmutable('2026-07-01 00:00:00',new DateTimeZone('UTC')));
        $winter=next_slot(['12:00'],new DateTimeImmutable('2026-01-01 00:00:00',new DateTimeZone('UTC')));
        $check($summer==='2026-07-01 16:00:00' && $winter==='2026-01-01 17:00:00','US daylight saving changes map to the correct Sri Lanka times');
        for ($i=1;$i<=3;$i++) {
            $source=str_pad((string)$i,11,'q');
            $q=$pdo->prepare('INSERT INTO jobs(channel_id,status,stage,source_video_id,title) VALUES (?,?,?,?,?)');
            $q->execute([$channel,$i<3?'published':'ready','uploader',$source,'Daily limit diagnostic']);$new=(int)$pdo->lastInsertId();
            $q=$pdo->prepare('INSERT INTO video_progress(job_id,channel_id,source_video_id,downloaded_at,edited_at,title_ready,published_at) VALUES (?,?,?,UTC_TIMESTAMP(),UTC_TIMESTAMP(),1,?)');
            $q->execute([$new,$channel,$source,$i<3?gmdate('Y-m-d H:i:s'):null]);
            if ($i===3) insert_task($pdo,'uploader',$channel,$new,'uploader:'.$new);
        }
        $check(claim_task($pdo,'diagnostic',['uploader'])===null,'A fourth post cannot start on the same Sri Lankan day');
        return ['ok'=>true,'checks'=>$checks,'fixtures'=>'rolled back'];
    } finally {
        if ($pdo->inTransaction()) $pdo->rollBack();
    }
}
