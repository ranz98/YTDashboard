<?php
declare(strict_types=1);
require __DIR__.'/private/core.php';
header('Cache-Control: no-store');
header('X-Frame-Options: DENY');
if (configuration()) { http_response_code(403); exit('Setup is locked. Sign in at index.php.'); }
session_open();
$bootstrap = is_file(__DIR__.'/private/bootstrap.php') ? require __DIR__.'/private/bootstrap.php' : [];
$error='';
if ($_SERVER['REQUEST_METHOD']==='POST') {
    try {
        if (!isset($bootstrap['setup_token']) || !hash_equals($bootstrap['setup_token'], (string)($_POST['setup_token']??''))) throw new RuntimeException('The setup token is incorrect.');
        if (!hash_equals($_SESSION['csrf'], (string)($_POST['csrf']??''))) throw new RuntimeException('Reload this page and try again.');
        $c=['db_host'=>trim($_POST['db_host']??'localhost'),'db_port'=>3306,'db_name'=>trim($_POST['db_name']??''),'db_user'=>trim($_POST['db_user']??''),'db_password'=>(string)($_POST['db_password']??''),'installed_at'=>gmdate('c')];
        if (!preg_match('/^[a-zA-Z0-9.-]+$/',$c['db_host']) || !preg_match('/^[a-zA-Z0-9_]+$/',$c['db_name'])) throw new RuntimeException('Invalid database host or name.');
        $email=trim($_POST['email']??''); $password=(string)($_POST['password']??'');
        if (!filter_var($email,FILTER_VALIDATE_EMAIL) || strlen($password)<14) throw new RuntimeException('Use a valid email and an admin password of at least 14 characters.');
        $lock=fopen(__DIR__.'/private/install.lock','c');
        if (!$lock || !flock($lock,LOCK_EX)) throw new RuntimeException('Cannot acquire the installation lock.');
        if (configuration()) throw new RuntimeException('Setup has already completed.');
        $pdo=db($c); schema($pdo);
        if ((int)$pdo->query('SELECT COUNT(*) FROM users')->fetchColumn()>0) throw new RuntimeException('An admin already exists. Restore the private configuration rather than reinstalling.');
        $hash=password_hash($password,PASSWORD_DEFAULT);
        $pdo->beginTransaction();
        $q=$pdo->prepare('INSERT INTO users(email,password_hash) VALUES (?,?)'); $q->execute([$email,$hash]);
        $id=(int)$pdo->lastInsertId();
        event($pdo,null,'system','success','Dashboard installed. Connect the VPS runner and Chrome extension to enable automation.');
        $contents="<?php\nreturn ".var_export($c,true).";\n";
        if (file_put_contents(__DIR__.'/private/config.php.tmp',$contents,LOCK_EX)===false || !rename(__DIR__.'/private/config.php.tmp',__DIR__.'/private/config.php')) throw new RuntimeException('Cannot save private configuration.');
        $pdo->commit(); flock($lock,LOCK_UN); fclose($lock);
        session_regenerate_id(true); $_SESSION['user_id']=$id; $_SESSION['email']=$email; $_SESSION['last_seen']=time();
        header('Location: index.php'); exit;
    } catch(Throwable $e) {
        if (isset($pdo) && $pdo->inTransaction()) $pdo->rollBack();
        $error=$e instanceof PDOException ? 'Database connection or schema setup failed. Check database details and permissions.' : $e->getMessage();
    }
}
?>
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Set up Astra</title><link rel="stylesheet" href="assets/app.css?v=0.1.1"></head><body class="auth-page"><main class="auth-card wide"><a class="brand" href="index.php"><span class="brand-mark">a</span> astra<span class="brand-sub">VIDEO</span></a><p class="eyebrow">FIRST-TIME SETUP</p><h1>Your control room, connected.</h1><p class="muted">Connect MySQL and create the administrator account. Setup locks automatically when complete.</p><?php if($error): ?><p class="error"><?=h($error)?></p><?php endif; ?><form method="post" class="form-grid"><input type="hidden" name="csrf" value="<?=h($_SESSION['csrf'])?>"><label class="full">Setup token<input name="setup_token" type="password" required autocomplete="off"></label><label>Database host<input name="db_host" value="localhost" required></label><label>Database name<input name="db_name" required></label><label>Database user<input name="db_user" required></label><label>Database password<input name="db_password" type="password" required autocomplete="off"></label><label>Admin email<input name="email" type="email" required></label><label>Admin password<input name="password" type="password" minlength="14" required autocomplete="new-password"></label><button class="button primary full" type="submit">Connect & finish setup →</button></form></main></body></html>
