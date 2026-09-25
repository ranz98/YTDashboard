<?php
declare(strict_types=1);
require __DIR__.'/private/core.php';
require __DIR__.'/private/operations.php';
header('Cache-Control: no-store');
if ($_SERVER['REQUEST_METHOD']!=='POST') json_response(['error'=>'POST required.'],405);
try {
    $pdo=db();
    $token=preg_replace('/^Bearer\s+/i','',$_SERVER['HTTP_AUTHORIZATION']??'');
    if (!preg_match('/^[a-f0-9]{64}$/',$token)) json_response(['error'=>'Worker authentication required.'],401);
    $q=$pdo->prepare('SELECT name FROM worker_keys WHERE token_hash=?');$q->execute([hash('sha256',$token)]);$worker=$q->fetchColumn();
    if (!$worker) json_response(['error'=>'Worker authentication required.'],401);
    $body=input();$action=$body['action']??'claim';
    $capabilities=array_values(array_intersect(['fetch','editor','uploader'],(array)($body['capabilities']??[])));
    if (!$capabilities) throw new InvalidArgumentException('Declare supported agents.');
    $q=$pdo->prepare('INSERT INTO workers(name,kind,version,last_seen) VALUES (?,?,?,UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE kind=VALUES(kind),version=VALUES(version),last_seen=UTC_TIMESTAMP()');
    $q->execute([$worker,implode(',',$capabilities),mb_substr((string)($body['version']??''),0,30)]);
    $pdo->beginTransaction();
    if ($action==='recover_claim') {
        $gate=lock_gate($pdo);
        $pdo->commit();json_response(['clear'=>empty($gate['current_task'])]);
    }
    if ($action==='claim') {
        $claimLease=$body['claim_lease']??null;
        if ($claimLease!==null && (!is_string($claimLease) || !preg_match('/^[a-f0-9]{64}$/',$claimLease))) throw new InvalidArgumentException('Invalid claim receipt.');
        $gate=lock_gate($pdo);
        $task=null;
        if ($claimLease && $gate['current_task']) {
            $q=$pdo->prepare('SELECT * FROM pipeline_tasks WHERE id=?');$q->execute([$gate['current_task']]);$current=$q->fetch();
            if ($current && $current['worker_name']===$worker && hash_equals((string)$current['lease_hash'],hash('sha256',$claimLease))) {
                $task=owned_task($pdo,$worker,(int)$current['id'],$claimLease);
                $task['lease']=$claimLease;unset($task['lease_hash']);
            }
        }
        tick_schedule($pdo);
        if (!$task) $task=claim_task($pdo,$worker,$capabilities,$claimLease);
        if ($task) {
            $q=$pdo->prepare('SELECT handle,destination,preset FROM channels WHERE id=?');$q->execute([$task['channel_id']]);$task['channel']=$q->fetch();
            if ($task['job_id']) {$q=$pdo->prepare('SELECT source_video_id,source_url,title FROM jobs WHERE id=?');$q->execute([$task['job_id']]);$task['video']=$q->fetch();}
            $task['fetch_limit']=5;
            if ($task['agent']==='fetch') {
                $q=$pdo->prepare('SELECT source_video_id FROM video_progress WHERE channel_id=? ORDER BY job_id DESC LIMIT 5000');$q->execute([$task['channel_id']]);
                $task['known_video_ids']=$q->fetchAll(PDO::FETCH_COLUMN);
            }
        }
        $pdo->commit();json_response(['task'=>$task,'server_time'=>gmdate('c')]);
    }
    if ($action==='heartbeat') {
        $task=owned_task($pdo,$worker,(int)($body['id']??0),(string)($body['lease']??''));
        $progress=max(0,min(99,(int)($body['progress']??0)));
        if ($progress!==(int)$task['progress'] && !empty($body['message'])) {
            event($pdo,$task['job_id']?(int)$task['job_id']:null,$task['agent'],'info',mb_substr((string)$body['message'],0,200));
        }
        $q=$pdo->prepare('UPDATE pipeline_tasks SET heartbeat_at=UTC_TIMESTAMP(),progress=? WHERE id=?');$q->execute([max(0,min(99,(int)($body['progress']??0))),$task['id']]);
        $pdo->commit();json_response(['stop_requested'=>(bool)$task['stop_requested']]);
    }
    if ($action==='complete') {
        // A lost acknowledgement must not repeat completion side effects.
        lock_gate($pdo);
        $q=$pdo->prepare('SELECT state,worker_name,lease_hash FROM pipeline_tasks WHERE id=? FOR UPDATE');$q->execute([(int)($body['id']??0)]);$previous=$q->fetch();
        if ($previous && in_array($previous['state'],['completed','failed','skipped','cancelled','needs_attention'],true) && $previous['worker_name']===$worker && hash_equals((string)$previous['lease_hash'],hash('sha256',(string)($body['lease']??'')))) {
            $pdo->commit();json_response(['ok'=>true]);
        }
        complete_task($pdo,$worker,$body);$pdo->commit();json_response(['ok'=>true]);
    }
    throw new InvalidArgumentException('Unknown worker action.');
} catch (InvalidArgumentException $error) {
    if(isset($pdo)&&$pdo->inTransaction())$pdo->rollBack();json_response(['error'=>$error->getMessage()],422);
} catch (Throwable $error) {
    if(isset($pdo)&&$pdo->inTransaction())$pdo->rollBack();error_log('Worker API: '.$error->getMessage());json_response(['error'=>'Worker request failed.'],500);
}
