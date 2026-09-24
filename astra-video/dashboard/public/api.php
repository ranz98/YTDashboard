<?php
declare(strict_types=1);
require __DIR__.'/private/core.php';
require __DIR__.'/private/operations.php';
header('Cache-Control: no-store');
$action=$_GET['action']??'overview';
if ($action==='health') json_response(['service'=>'astra-video','version'=>'0.2.0','installed'=>configuration()!==null]);
if (!configuration()) json_response(['error'=>'Complete setup first.'],503);
$read=['overview','jobs','channels','schedules','logs','analytics','settings','operations','errors','video_checks'];
if (!in_array($action,$read,true)) require_admin();
try {
    $pdo=db();
    if (in_array($action,$read,true) && $_SERVER['REQUEST_METHOD']!=='GET') json_response(['error'=>'Method not allowed.'],405);
    if (!in_array($action,$read,true) && $_SERVER['REQUEST_METHOD']!=='POST') json_response(['error'=>'Method not allowed.'],405);
    if ($action==='operations') json_response(operations_snapshot($pdo));
    if ($action==='errors') {
        $events=$pdo->query("SELECT e.*,c.name channel_name,j.title FROM events e LEFT JOIN jobs j ON j.id=e.job_id LEFT JOIN channels c ON c.id=j.channel_id WHERE e.level IN ('error','warning') ORDER BY e.id DESC LIMIT 200")->fetchAll();
        $tasks=$pdo->query("SELECT t.id,t.agent,t.state,t.reason,t.job_id,t.started_at,t.finished_at,c.name channel_name FROM pipeline_tasks t JOIN channels c ON c.id=t.channel_id WHERE t.state IN ('failed','blocked','skipped','needs_attention') OR (t.state='running' AND t.heartbeat_at<UTC_TIMESTAMP()-INTERVAL 120 SECOND) ORDER BY t.id DESC LIMIT 200")->fetchAll();
        json_response(['events'=>$events,'tasks'=>$tasks]);
    }
    if ($action==='video_checks') {
        $rows=$pdo->query('SELECT j.*,c.name channel_name,v.downloaded_at,v.edited_at,v.title_ready,v.published_at,v.blocked_reason FROM jobs j JOIN channels c ON c.id=j.channel_id LEFT JOIN video_progress v ON v.job_id=j.id WHERE j.source_video_id IS NOT NULL ORDER BY j.id DESC LIMIT 200')->fetchAll();
        json_response(['items'=>$rows]);
    }
    if ($action==='overview') {
        $stats=$pdo->query("SELECT COUNT(*) total,COALESCE(SUM(status='published'),0) published,COALESCE(SUM(status='published' AND DATE(DATE_ADD(finished_at,INTERVAL 330 MINUTE))=DATE(DATE_ADD(UTC_TIMESTAMP(),INTERVAL 330 MINUTE))),0) published_today,COALESCE(SUM(status='queued'),0) queued,COALESCE(SUM(status IN ('failed','needs_attention')),0) failed,COALESCE(SUM(status IN ('discovering','downloading','editing','uploading','verifying')),0) active FROM jobs")->fetch();
        $stats['channels']=(int)$pdo->query('SELECT COUNT(*) FROM channels WHERE enabled=1')->fetchColumn();
        $workers=$pdo->query('SELECT *,TIMESTAMPDIFF(SECOND,last_seen,UTC_TIMESTAMP()) age_seconds FROM workers')->fetchAll();
        $jobs=$pdo->query('SELECT j.*,c.name channel_name,c.handle FROM jobs j JOIN channels c ON c.id=j.channel_id ORDER BY j.id DESC LIMIT 8')->fetchAll();
        $events=$pdo->query('SELECT * FROM events ORDER BY id DESC LIMIT 12')->fetchAll();
        json_response(['stats'=>$stats,'workers'=>$workers,'jobs'=>$jobs,'events'=>$events,'time'=>gmdate('c'),'automation_available'=>false]);
    }
    if ($action==='jobs') json_response(['items'=>$pdo->query('SELECT j.*,c.name channel_name,c.handle FROM jobs j JOIN channels c ON c.id=j.channel_id ORDER BY j.id DESC LIMIT 200')->fetchAll()]);
    if ($action==='channels') json_response(['items'=>$pdo->query('SELECT c.*,(SELECT COUNT(*) FROM jobs j WHERE j.channel_id=c.id) jobs_count FROM channels c ORDER BY c.id DESC')->fetchAll()]);
    if ($action==='schedules') json_response(['items'=>$pdo->query('SELECT s.*,c.name channel_name,c.handle FROM schedules s JOIN channels c ON c.id=s.channel_id ORDER BY s.id DESC')->fetchAll()]);
    if ($action==='logs') {
        $after=max(0,(int)($_GET['after']??0)); $job=max(0,(int)($_GET['job']??0));
        if($after===0){
            $q=$pdo->prepare('SELECT * FROM (SELECT * FROM events WHERE (?=0 OR job_id=?) ORDER BY id DESC LIMIT 200) recent ORDER BY id'); $q->execute([$job,$job]);
        } else { $q=$pdo->prepare('SELECT * FROM events WHERE id>? AND (?=0 OR job_id=?) ORDER BY id LIMIT 200'); $q->execute([$after,$job,$job]); }
        json_response(['items'=>$q->fetchAll(),'time'=>gmdate('c')]);
    }
    if ($action==='analytics') {
        $days=$pdo->query("SELECT DATE(DATE_ADD(created_at,INTERVAL 330 MINUTE)) day,COUNT(*) jobs,SUM(status='published') published,SUM(status='failed') failed FROM jobs WHERE created_at>=DATE(DATE_ADD(UTC_TIMESTAMP(),INTERVAL 330 MINUTE))-INTERVAL 330 MINUTE-INTERVAL 29 DAY GROUP BY DATE(DATE_ADD(created_at,INTERVAL 330 MINUTE)) ORDER BY day")->fetchAll();
        $totals=$pdo->query("SELECT COUNT(*) jobs,COALESCE(SUM(status='published'),0) published,COALESCE(SUM(status='failed'),0) failed,ROUND(AVG(CASE WHEN status='published' THEN TIMESTAMPDIFF(SECOND,created_at,finished_at) END)) average_seconds FROM jobs")->fetch();
        json_response(['days'=>$days,'totals'=>$totals]);
    }
    if ($action==='settings') json_response(['version'=>'0.2.0','database'=>'Connected','timezone'=>'Asia/Colombo','automation_available'=>false,'workers'=>$pdo->query('SELECT name,kind,version,last_seen FROM workers ORDER BY id')->fetchAll()]);
    $body=input();
    if (in_array($action,['operations_migrate','pipeline_control','agent_control','agent_schedule','agent_run','task_skip','task_retry'],true)) json_response(handle_operations($pdo,$action,$body));
    if ($action==='queue_checks') {
        require __DIR__.'/private/queue-checks.php';
        json_response(run_queue_checks($pdo));
    }
    if ($action==='worker_register') {
        $name=trim((string)($body['name']??''));
        if (!preg_match('/^[a-zA-Z0-9_-]{3,60}$/',$name)) throw new InvalidArgumentException('Use a short worker name.');
        $token=bin2hex(random_bytes(32));
        $q=$pdo->prepare('INSERT INTO worker_keys(name,token_hash) VALUES (?,?) ON DUPLICATE KEY UPDATE token_hash=VALUES(token_hash)');$q->execute([$name,hash('sha256',$token)]);
        json_response(['name'=>$name,'token'=>$token]);
    }
    if ($action==='channel_save') {
        $name=trim((string)($body['name']??'')); $handle=trim((string)($body['handle']??'')); $destination=trim((string)($body['destination']??'')); $preset=(string)($body['preset']??'vivid');
        if(!$name || mb_strlen($name)>120 || !preg_match('/^@[\p{L}\p{N}_.-]{2,100}$/u',$handle) || mb_strlen($destination)>120) throw new InvalidArgumentException('Enter a name, a valid @channel handle, and a destination under 120 characters.');
        if(!in_array($preset,['vivid','punch','warm','cool','bright','fade','cinematic','clarity','bw','vignette','none'],true)) throw new InvalidArgumentException('Choose a valid editing preset.');
        $q=$pdo->prepare('INSERT INTO channels(name,handle,destination,preset) VALUES (?,?,?,?)'); $q->execute([$name,$handle,$destination,$preset]); event($pdo,null,'dashboard','info','Channel added: '.$handle); json_response(['ok'=>true]);
    }
    if ($action==='channel_toggle') {
        $q=$pdo->prepare('UPDATE channels SET enabled=1-enabled WHERE id=?'); $q->execute([(int)($body['id']??0)]); json_response(['ok'=>true]);
    }
    if ($action==='queue') {
        $pdo->beginTransaction(); $id=enqueue($pdo,(int)($body['channel_id']??0)); $pdo->commit(); json_response(['ok'=>true,'id'=>$id]);
    }
    if ($action==='schedule_save') {
        $interval=(int)($body['interval_minutes']??60); $channel=(int)($body['channel_id']??0);
        if($interval<5 || $interval>43200) throw new InvalidArgumentException('Interval must be between 5 and 43,200 minutes.');
        $q=$pdo->prepare('SELECT id FROM channels WHERE id=?'); $q->execute([$channel]); if(!$q->fetch()) throw new InvalidArgumentException('Select a channel.');
        $q=$pdo->prepare('INSERT INTO schedules(channel_id,interval_minutes,next_run) VALUES (?,?,UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE interval_minutes=VALUES(interval_minutes),enabled=1,next_run=UTC_TIMESTAMP()'); $q->execute([$channel,$interval]); event($pdo,null,'dashboard','info','Schedule saved. Execution requires the VPS runner.'); json_response(['ok'=>true]);
    }
    if ($action==='schedule_toggle') {
        $q=$pdo->prepare('UPDATE schedules SET enabled=1-enabled WHERE id=?'); $q->execute([(int)($body['id']??0)]); json_response(['ok'=>true]);
    }
    if ($action==='job_cancel') {
        $id=(int)($body['id']??0); $q=$pdo->prepare("UPDATE jobs SET status='cancelled',finished_at=UTC_TIMESTAMP() WHERE id=? AND status='queued'"); $q->execute([$id]);
        if(!$q->rowCount()) throw new InvalidArgumentException('Only queued jobs can be cancelled in this release.'); event($pdo,$id,'dashboard','warning','Queued job cancelled.'); json_response(['ok'=>true]);
    }
    if ($action==='password_change') {
        session_open(); $id=(int)$_SESSION['user_id']; session_write_close();
        $q=$pdo->prepare('SELECT password_hash FROM users WHERE id=?'); $q->execute([$id]);
        if(!password_verify((string)($body['current']??''),(string)$q->fetchColumn())) throw new InvalidArgumentException('Current password is incorrect.');
        $next=(string)($body['password']??''); if(strlen($next)<14) throw new InvalidArgumentException('Use at least 14 characters.');
        $q=$pdo->prepare('UPDATE users SET password_hash=? WHERE id=?'); $q->execute([password_hash($next,PASSWORD_DEFAULT),$id]); json_response(['ok'=>true]);
    }
    if ($action==='logout') { session_open(); $_SESSION=[]; session_destroy(); json_response(['ok'=>true]); }
    json_response(['error'=>'Unknown action.'],404);
} catch(InvalidArgumentException $e) {
    if(isset($pdo)&&$pdo->inTransaction()) $pdo->rollBack(); json_response(['error'=>$e->getMessage()],422);
} catch(Throwable $e) {
    if(isset($pdo)&&$pdo->inTransaction()) $pdo->rollBack();
    $duplicate=$e instanceof PDOException && $e->getCode()==='23000';
    error_log('Astra API error: '.$e->getMessage());
    if (!$duplicate && isset($pdo)) {
        try { event($pdo,null,'api','error','A dashboard request failed ('.preg_replace('/[^a-z_]/','',$action).'). Check the server log for details.'); } catch (Throwable) {}
    }
    json_response(['error'=>$duplicate?'That entry already exists.':'The request could not be completed. Please try again.'],$duplicate?409:500);
}
