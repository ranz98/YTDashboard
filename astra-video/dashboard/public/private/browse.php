<?php
declare(strict_types=1);

function browse_items(PDO $pdo, string $kind, array $query): array {
    $videos=$kind==='videos';
    $stage=(string)($query['stage']??'all');
    $allowed=$videos?['all','fetched','edited','uploaded']:['all','fetch','editor','uploader'];
    if (!in_array($stage,$allowed,true)) throw new InvalidArgumentException('Invalid stage filter.');
    $activity=$videos?'j.updated_at':'COALESCE(t.finished_at,t.started_at,t.created_at)';
    $stamp=$videos?(['fetched'=>'v.downloaded_at','edited'=>'v.edited_at','uploaded'=>'v.published_at'][$stage]??'v.downloaded_at'):$activity;
    $where=[];$values=[];
    if ($videos) {
        $from='jobs j JOIN video_progress v ON v.job_id=j.id JOIN channels c ON c.id=j.channel_id';
        $columns='j.*,c.name channel_name,v.downloaded_at,v.edited_at,v.title_ready,v.published_at,v.blocked_reason';
        if ($stage!=='all') $where[]=$stamp.' IS NOT NULL';
        $id='j.id';$created='j.created_at';
    } else {
        $from='pipeline_tasks t JOIN channels c ON c.id=t.channel_id LEFT JOIN jobs j ON j.id=t.job_id';
        $columns='t.id,t.agent,t.state,t.job_id,t.created_at,t.scheduled_at,t.started_at,t.finished_at,t.reason,c.name channel_name,j.title';
        if ($stage!=='all') {$where[]='t.agent=?';$values[]=$stage;}
        $state=(string)($query['state']??'all');
        if (!in_array($state,['all','queued','running','completed','failed','skipped','blocked','cancelled','needs_attention'],true)) throw new InvalidArgumentException('Invalid task status.');
        if ($state!=='all') {$where[]='t.state=?';$values[]=$state;}
        $id='t.id';$created='t.created_at';
    }
    $zone=new DateTimeZone('Asia/Colombo');
    $today=new DateTimeImmutable('today',$zone);
    $range=(string)($query['range']??'all');
    $start=null;$end=null;
    if ($range==='today') {$start=$today;$end=$today->modify('+1 day');}
    elseif ($range==='yesterday') {$start=$today->modify('-1 day');$end=$today;}
    elseif ($range==='week') {$start=$today->modify('-'.((int)$today->format('N')-1).' days');$end=$today->modify('+1 day');}
    elseif ($range==='month') {$start=$today->modify('first day of this month');$end=$today->modify('+1 day');}
    elseif ($range==='custom') {
        foreach (['from','to'] as $key) {
            $raw=(string)($query[$key]??'');
            $parsed=DateTimeImmutable::createFromFormat('!Y-m-d',$raw,$zone);
            if (!$parsed || $parsed->format('Y-m-d')!==$raw) throw new InvalidArgumentException('Choose valid start and end dates.');
            if ($key==='from') $start=$parsed; else $end=$parsed->modify('+1 day');
        }
        if ($start >= $end) throw new InvalidArgumentException('End date must be on or after start date.');
    } elseif ($range!=='all') throw new InvalidArgumentException('Invalid date range.');
    if ($start) {
        $where[]="$stamp >= ? AND $stamp < ?";
        $utc=new DateTimeZone('UTC');
        $values[]=$start->setTimezone($utc)->format('Y-m-d H:i:s');
        $values[]=$end->setTimezone($utc)->format('Y-m-d H:i:s');
    }
    $sort=(string)($query['sort']??'activity');
    if (!in_array($sort,['activity','latest','oldest'],true)) throw new InvalidArgumentException('Invalid sort order.');
    $order=$sort==='activity'?"$activity DESC,$id DESC":($sort==='oldest'?"$created ASC,$id ASC":"$created DESC,$id DESC");
    $filter=$where?' WHERE '.implode(' AND ',$where):'';
    $q=$pdo->prepare("SELECT COUNT(*) FROM $from$filter");$q->execute($values);$total=(int)$q->fetchColumn();
    $offset=max(0,(int)($query['offset']??0));
    $q=$pdo->prepare("SELECT $columns,$activity activity_at FROM $from$filter ORDER BY $order LIMIT 100 OFFSET $offset");
    $q->execute($values);$items=$q->fetchAll();
    return ['items'=>$items,'total'=>$total,'has_more'=>$offset+count($items)<$total];
}
