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
    if ($action==='claim') {
        tick_schedule($pdo);
        $task=claim_task($pdo,$worker,$capabilities);
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
        $q=$pdo->prepare('UPDATE pipeline_tasks SET heartbeat_at=UTC_TIMESTAMP(),progress=? WHERE id=?');$q->execute([max(0,min(99,(int)($body['progress']??0))),$task['id']]);
        $pdo->commit();json_response(['stop_requested'=>(bool)$task['stop_requested']]);
    }
    if ($action==='complete') {
        complete_task($pdo,$worker,$body);$pdo->commit();json_response(['ok'=>true]);
    }
    throw new InvalidArgumentException('Unknown worker action.');
} catch (InvalidArgumentException $error) {
    if(isset($pdo)&&$pdo->inTransaction())$pdo->rollBack();json_response(['error'=>$error->getMessage()],422);
} catch (Throwable $error) {
    if(isset($pdo)&&$pdo->inTransaction())$pdo->rollBack();error_log('Worker API: '.$error->getMessage());json_response(['error'=>'Worker request failed.'],500);
}
