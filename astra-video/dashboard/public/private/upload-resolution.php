<?php
declare(strict_types=1);

function youtube_video_id(string $url): string {
    $parts=parse_url(trim($url));
    if (!$parts || ($parts['scheme']??'')!=='https' || isset($parts['user']) || isset($parts['pass'])) throw new InvalidArgumentException('Paste an HTTPS YouTube video link.');
    $host=strtolower($parts['host']??'');$path=$parts['path']??'';$id='';
    if ($host==='youtu.be') $id=trim($path,'/');
    elseif (in_array($host,['youtube.com','www.youtube.com','m.youtube.com'],true)) {
        if ($path==='/watch') {parse_str($parts['query']??'',$query);$id=$query['v']??'';}
        elseif (preg_match('~^/shorts/([\w-]{11})/?$~',$path,$match)) $id=$match[1];
    }
    if (!is_string($id) || !preg_match('/^[A-Za-z0-9_-]{11}$/',$id)) throw new InvalidArgumentException('Use the watch or Shorts link for this uploaded video.');
    return $id;
}

// The caller holds the execution gate and commits the audit with these changes.
function resolve_upload(PDO $pdo, array $gate, array $body): void {
    $id=(int)($body['id']??0);$outcome=$body['outcome']??'';
    if (!in_array($outcome,['published','retry','hold'],true)) throw new InvalidArgumentException('Choose how to resolve the upload.');
    if (($body['confirmed']??false)!==true) throw new InvalidArgumentException('Confirm that you checked this video in YouTube Studio.');
    $q=$pdo->prepare('SELECT * FROM pipeline_tasks WHERE id=? FOR UPDATE');$q->execute([$id]);$task=$q->fetch();
    if (!$task || $task['agent']!=='uploader' || !$task['job_id']) throw new InvalidArgumentException('Upload task not found.');
    if ((int)($gate['current_task']??0)===$id || !in_array($task['state'],['needs_attention','failed','skipped','cancelled'],true)) throw new InvalidArgumentException('Only a stopped upload can be resolved. Refresh the queue.');
    $job=(int)$task['job_id'];
    $q=$pdo->prepare('SELECT * FROM video_progress WHERE job_id=? FOR UPDATE');$q->execute([$job]);$video=$q->fetch();
    if (!$video || $video['published_at']) throw new InvalidArgumentException('This video is missing or already marked published.');
    $q=$pdo->prepare("SELECT id FROM pipeline_tasks WHERE job_id=? AND agent='uploader' AND state IN ('queued','running') AND id<>? LIMIT 1");$q->execute([$job,$id]);
    if ($q->fetchColumn()) throw new InvalidArgumentException('Another upload for this video is already pending.');
    if ($outcome==='published') {
        $youtubeId=youtube_video_id((string)($body['url']??''));
        $url='https://www.youtube.com/watch?v='.$youtubeId;
        $q=$pdo->prepare('SELECT id FROM jobs WHERE published_url=? AND id<>? LIMIT 1');$q->execute([$url,$job]);
        if ($q->fetchColumn()) throw new InvalidArgumentException('That YouTube link is already assigned to another video.');
        $raw=(string)($body['published_at']??'');
        $when=DateTimeImmutable::createFromFormat('!Y-m-d\TH:i',$raw,new DateTimeZone(LOCAL_ZONE));
        if (!$when || $when->format('Y-m-d\TH:i')!==$raw || $when>new DateTimeImmutable('now')) throw new InvalidArgumentException('Enter the actual publication date and time in Sri Lanka time.');
        $stamp=$when->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i:s');
        $q=$pdo->prepare("UPDATE jobs SET status='published',stage='uploader',progress=100,published_url=?,finished_at=?,error=NULL WHERE id=?");$q->execute([$url,$stamp,$job]);
        $q=$pdo->prepare('UPDATE video_progress SET published_at=?,blocked_reason=NULL WHERE job_id=?');$q->execute([$stamp,$job]);
        $q=$pdo->prepare("UPDATE pipeline_tasks SET state='completed',progress=100,reason=NULL,finished_at=?,lease_hash=NULL WHERE id=?");$q->execute([$stamp,$id]);
        event($pdo,$job,'uploader','success','Task #'.$id.' reconciled: administrator confirmed Public in YouTube Studio. '.$url);
    } elseif ($outcome==='retry') {
        if (!$video['edited_at'] || !(int)$video['title_ready']) throw new InvalidArgumentException('A verified edit and title are required before retrying.');
        $q=$pdo->prepare("UPDATE pipeline_tasks SET state='queued',scheduled_at=UTC_TIMESTAMP(),started_at=NULL,finished_at=NULL,heartbeat_at=NULL,worker_name=NULL,lease_hash=NULL,stop_requested=0,progress=0,reason=NULL WHERE id=?");$q->execute([$id]);
        $q=$pdo->prepare("UPDATE jobs SET status='ready',stage='uploader',error=NULL WHERE id=?");$q->execute([$job]);
        $q=$pdo->prepare('UPDATE video_progress SET blocked_reason=NULL WHERE job_id=?');$q->execute([$job]);
        event($pdo,$job,'uploader','warning','Task #'.$id.' retry authorized: administrator confirmed no existing upload remains in Studio.');
    } else {
        $reason='Upload held by administrator. Existing YouTube outcome needs review; do not upload this video again.';
        $q=$pdo->prepare("UPDATE pipeline_tasks SET state='cancelled',reason=?,lease_hash=NULL WHERE id=?");$q->execute([$reason,$id]);
        $q=$pdo->prepare("UPDATE jobs SET status='cancelled',error=? WHERE id=?");$q->execute([$reason,$job]);
        $q=$pdo->prepare('UPDATE video_progress SET blocked_reason=? WHERE job_id=?');$q->execute([$reason,$job]);
        event($pdo,$job,'uploader','info','Task #'.$id.' cleared from the upload queue; video remains held for review.');
    }
}
