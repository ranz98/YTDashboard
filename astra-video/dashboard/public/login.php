<?php
declare(strict_types=1);
require __DIR__.'/private/core.php';
header('Cache-Control: no-store'); header('X-Frame-Options: DENY');
if (!configuration()) { header('Location: setup.php'); exit; }
session_open(); $error='';
if ($_SERVER['REQUEST_METHOD']==='POST') {
    try {
        if (!hash_equals($_SESSION['csrf'], (string)($_POST['csrf']??''))) throw new RuntimeException('Reload the page and try again.');
        $pdo=db(); $address=hash('sha256',$_SERVER['REMOTE_ADDR']??'unknown');
        $q=$pdo->prepare('INSERT INTO login_attempts(address_hash,attempts,window_start) VALUES (?,0,UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE address_hash=address_hash'); $q->execute([$address]);
        $pdo->beginTransaction();
        $q=$pdo->prepare('SELECT attempts,window_start FROM login_attempts WHERE address_hash=? FOR UPDATE'); $q->execute([$address]); $limit=$q->fetch();
        if (strtotime($limit['window_start'].' UTC')<time()-900) {
            $q=$pdo->prepare('UPDATE login_attempts SET attempts=0,window_start=UTC_TIMESTAMP() WHERE address_hash=?'); $q->execute([$address]); $limit['attempts']=0;
        }
        if ($limit['attempts']>=10) { $pdo->commit(); throw new RuntimeException('Too many attempts. Try again in 15 minutes.'); }
        $q=$pdo->prepare('UPDATE login_attempts SET attempts=attempts+1 WHERE address_hash=?'); $q->execute([$address]); $pdo->commit();
        $q=$pdo->prepare('SELECT id,email,password_hash FROM users WHERE email=?'); $q->execute([trim($_POST['email']??'')]); $user=$q->fetch();
        if (!$user || !password_verify((string)($_POST['password']??''),$user['password_hash'])) throw new RuntimeException('Email or password is incorrect.');
        $q=$pdo->prepare('DELETE FROM login_attempts WHERE address_hash=?'); $q->execute([$address]);
        session_regenerate_id(true); $_SESSION['user_id']=(int)$user['id']; $_SESSION['email']=$user['email']; $_SESSION['last_seen']=time();
        header('Location: index.php'); exit;
    } catch(Throwable $e) { if(isset($pdo)&&$pdo->inTransaction()) $pdo->rollBack(); $error=$e instanceof PDOException?'Database unavailable. Please try again shortly.':$e->getMessage(); }
}
?>
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in · Astra Video</title><link rel="stylesheet" href="assets/app.css?v=0.1.1"><link rel="stylesheet" href="assets/dark.css?v=1"></head><body class="auth-page"><main class="auth-card"><a class="brand" href="index.php"><span class="brand-mark">a</span> astra<span class="brand-sub">VIDEO</span></a><p class="eyebrow">YOUR VIDEO OPERATIONS</p><h1>Back in control.</h1><p class="muted">Sign in to manage channels, jobs and your publishing pipeline.</p><?php if($error): ?><p class="error" role="alert"><?=h($error)?></p><?php endif; ?><form method="post"><input type="hidden" name="csrf" value="<?=h($_SESSION['csrf'])?>"><label>Email address<input name="email" type="email" autocomplete="username" required autofocus></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><button class="button primary" type="submit">Open dashboard →</button></form><p class="auth-foot">ASTRA VIDEO / PRIVATE WORKSPACE</p></main></body></html>
