<?php
declare(strict_types=1);

function upload_resolution_checks(PDO $pdo): array {
    require_once __DIR__.'/upload-resolution.php';
    $checks=[];
    $check=function(bool $ok,string $name) use (&$checks): void {if (!$ok) throw new RuntimeException($name);$checks[]=$name;};
    $reject=function(callable $run,string $name) use ($check): void {
        $caught=false;try {$run();}catch(InvalidArgumentException){$caught=true;}$check($caught,$name);
    };
    $pdo->beginTransaction();
    try {
        $gate=lock_gate($pdo);
        $q=$pdo->prepare('INSERT INTO channels(name,handle) VALUES (?,?)');$q->execute(['Upload diagnostic','@check_'.bin2hex(random_bytes(6))]);$channel=(int)$pdo->lastInsertId();
        $q=$pdo->prepare("INSERT INTO jobs(channel_id,status,stage,title) VALUES (?,'needs_attention','uploader','Diagnostic')");$q->execute([$channel]);$job=(int)$pdo->lastInsertId();
        $q=$pdo->prepare("INSERT INTO video_progress(job_id,channel_id,source_video_id,downloaded_at,edited_at,title_ready,blocked_reason) VALUES (?,?,'abcdefghijk',UTC_TIMESTAMP(),UTC_TIMESTAMP(),1,'Uncertain')");$q->execute([$job,$channel]);
        $id=insert_task($pdo,'uploader',$channel,$job,'diagnostic:'.bin2hex(random_bytes(12)));
        $pdo->exec("UPDATE pipeline_tasks SET state='needs_attention' WHERE id=$id");
        $body=['id'=>$id,'outcome'=>'retry','confirmed'=>true];
        $reject(fn()=>resolve_upload($pdo,$gate,array_replace($body,['confirmed'=>false])),'Explicit Studio confirmation required');
        $reject(fn()=>resolve_upload($pdo,['current_task'=>$id],$body),'Active uploads cannot be resolved');
        resolve_upload($pdo,$gate,array_replace($body,['outcome'=>'hold']));
        $check((bool)$pdo->query("SELECT blocked_reason FROM video_progress WHERE job_id=$job")->fetchColumn(),'Holding keeps the video blocked');
        resolve_upload($pdo,$gate,$body);
        $check($pdo->query("SELECT state FROM pipeline_tasks WHERE id=$id")->fetchColumn()==='queued','Verified absence permits retry');
        $check($pdo->query("SELECT status FROM jobs WHERE id=$job")->fetchColumn()==='ready','Retry preserves the verified edit');
        $reject(fn()=>resolve_upload($pdo,$gate,$body),'Double retry is rejected');
        $pdo->exec("UPDATE pipeline_tasks SET state='needs_attention' WHERE id=$id");
        $published=array_replace($body,['outcome'=>'published','url'=>'https://www.youtube.com/shorts/abcdefghijk','published_at'=>(new DateTimeImmutable('now',new DateTimeZone(LOCAL_ZONE)))->modify('-1 minute')->format('Y-m-d\TH:i')]);
        $reject(fn()=>resolve_upload($pdo,$gate,array_replace($published,['url'=>'https://example.com/watch?v=abcdefghijk'])),'Only YouTube links accepted');
        $reject(fn()=>resolve_upload($pdo,$gate,array_replace($published,['published_at'=>'2099-01-01T12:00'])),'Future publication times rejected');
        resolve_upload($pdo,$gate,$published);
        $check($pdo->query("SELECT state FROM pipeline_tasks WHERE id=$id")->fetchColumn()==='completed','Existing publication completes upload task');
        $check((bool)$pdo->query("SELECT published_at IS NOT NULL AND blocked_reason IS NULL FROM video_progress WHERE job_id=$job")->fetchColumn(),'Published checkmark set and hold cleared');
        $check($pdo->query("SELECT published_url FROM jobs WHERE id=$job")->fetchColumn()==='https://www.youtube.com/watch?v=abcdefghijk','Canonical publication link saved');
        $check(lock_gate($pdo)===$gate,'Live execution slot unchanged');
        return ['ok'=>true,'checks'=>$checks,'fixtures'=>'rolled back'];
    } finally {$pdo->rollBack();}
}
