<?php
declare(strict_types=1);

function configuration(): ?array {
    $path = __DIR__ . '/config.php';
    return is_file($path) ? require $path : null;
}

function db(?array $config = null): PDO {
    static $connection;
    if ($connection && $config === null) return $connection;
    $c = $config ?? configuration();
    if (!$c) throw new RuntimeException('Installation is incomplete.');
    $pdo = new PDO('mysql:host='.$c['db_host'].';port='.$c['db_port'].';dbname='.$c['db_name'].';charset=utf8mb4', $c['db_user'], $c['db_password'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
    $pdo->exec("SET time_zone = '+00:00'");
    if ($config === null) $connection = $pdo;
    return $pdo;
}

function session_open(): void {
    if (session_status() === PHP_SESSION_ACTIVE) return;
    ini_set('session.use_strict_mode', '1');
    session_name('astra_session');
    session_set_cookie_params(['lifetime'=>0,'path'=>'/astra/','secure'=>true,'httponly'=>true,'samesite'=>'Strict']);
    session_start();
    if (empty($_SESSION['csrf'])) $_SESSION['csrf'] = bin2hex(random_bytes(32));
}

function json_response(array $data, int $code = 200): never {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}

function h(string $s): string { return htmlspecialchars($s, ENT_QUOTES, 'UTF-8'); }

function input(): array {
    if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 262144) json_response(['error'=>'Request too large.'], 413);
    $raw = file_get_contents('php://input');
    $value = json_decode($raw ?: '{}', true);
    if (!is_array($value)) json_response(['error'=>'Expected a JSON object.'], 400);
    return $value;
}

function require_admin(): void {
    session_open();
    if (empty($_SESSION['user_id'])) json_response(['error'=>'Sign in to continue.'], 401);
    if (($_SESSION['last_seen'] ?? 0) < time()-28800) {
        session_destroy(); json_response(['error'=>'Session expired. Sign in again.'], 401);
    }
    $_SESSION['last_seen'] = time();
    if ($_SERVER['REQUEST_METHOD'] !== 'GET' && !hash_equals($_SESSION['csrf'], $_SERVER['HTTP_X_CSRF_TOKEN'] ?? '')) json_response(['error'=>'Invalid request token.'], 403);
    session_write_close();
}

function event(PDO $pdo, ?int $job, string $source, string $level, string $message): void {
    $q=$pdo->prepare('INSERT INTO events (job_id,source,level,message) VALUES (?,?,?,?)');
    $q->execute([$job,$source,$level,mb_substr($message,0,4000)]);
}

function schema(PDO $pdo): void {
    $sql = file_get_contents(__DIR__.'/schema.sql');
    foreach (explode(';', $sql) as $statement) if (trim($statement)) $pdo->exec($statement);
    require_once __DIR__.'/operations.php';
    migrate_operations($pdo);
}

function enqueue(PDO $pdo, int $channelId): int {
    lock_gate($pdo);
    $q=$pdo->prepare('SELECT id,enabled FROM channels WHERE id=? FOR UPDATE'); $q->execute([$channelId]);
    $channel=$q->fetch();
    if (!$channel || !$channel['enabled']) throw new InvalidArgumentException('Choose an enabled channel.');
    $q=$pdo->prepare("SELECT id FROM pipeline_tasks WHERE channel_id=? AND agent='fetch' AND state IN ('queued','running') LIMIT 1");
    $q->execute([$channelId]); $old=$q->fetchColumn();
    if ($old) return (int)$old;
    $id=insert_task($pdo,'fetch',$channelId,null,'manual:'.bin2hex(random_bytes(12)));
    event($pdo,null,'fetch','info','Fetch task #'.$id.' queued for the latest five videos.');
    return $id;
}
