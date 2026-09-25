<?php
declare(strict_types=1);
require __DIR__.'/private/core.php';
header('Cache-Control: no-store'); header('X-Frame-Options: DENY');
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
if(!configuration()){header('Location: setup.php');exit;}
session_open();
$isAdmin=!empty($_SESSION['user_id']) && ($_SESSION['last_seen']??0)>=time()-28800;
if($isAdmin) $_SESSION['last_seen']=time();
$csrf=$_SESSION['csrf']; $email=$isAdmin?$_SESSION['email']:'';session_write_close();
?>
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="csrf-token" content="<?=h($csrf)?>"><meta name="access-mode" content="<?=$isAdmin?'admin':'public'?>"><meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#0b0e14"><title>Overview · Astra Video</title><link rel="stylesheet" href="assets/app.css?v=7"><script defer src="assets/operations.js?v=10"></script><script defer src="assets/browse.js?v=3"></script><script defer src="assets/app.js?v=5"></script></head>
<body>
<aside class="sidebar">
  <a class="brand" href="#overview"><span class="brand-mark">A</span><span class="brand-name">Astra<small>Video automation</small></span></a>
  <nav aria-label="Main navigation">
    <p class="nav-label">Monitor</p>
    <a href="#overview" data-page="overview"><i data-icon="overview"></i><span>Overview</span></a>
    <a href="#jobs" data-page="jobs"><i data-icon="queue"></i><span>Queue</span><b id="nav-queue" hidden>0</b></a>
    <a href="#library" data-page="library"><i data-icon="video"></i><span>Videos</span></a>
    <a href="#errors" data-page="errors"><i data-icon="alert"></i><span>Errors</span><b id="nav-errors" class="is-alert" hidden>0</b></a>
    <p class="nav-label">Setup</p>
    <a href="#channels" data-page="channels"><i data-icon="channels"></i><span>Channels</span></a>
    <a href="#schedules" data-page="schedules"><i data-icon="clock"></i><span>Schedule</span></a>
    <a href="#settings" data-page="settings"><i data-icon="settings"></i><span>Settings</span></a>
    <p class="nav-label">Insights</p>
    <a href="#console" data-page="console"><i data-icon="console"></i><span>Console</span></a>
    <a href="#analytics" data-page="analytics"><i data-icon="analytics"></i><span>Analytics</span></a>
  </nav>
  <div class="sidebar-bottom">
    <div class="worker-card"><span class="status-dot amber"></span><strong>Checking VPS…</strong><small>Status loads with the overview</small></div>
    <?php if($isAdmin): ?><button id="logout" class="profile" title="Sign out"><span class="profile-avatar">A</span><span class="profile-text">Administrator<small><?=h($email)?></small></span><i data-icon="logout"></i></button><?php else: ?><a class="profile" href="login.php"><span class="profile-avatar"><i data-icon="lock"></i></span><span class="profile-text">Read-only view<small>Sign in to manage</small></span></a><?php endif; ?>
  </div>
</aside>
<button id="sidebar-scrim" class="sidebar-scrim" aria-label="Close navigation" hidden></button>
<div class="main-shell">
  <header class="topbar">
    <button id="menu-toggle" class="icon-button mobile-only" aria-label="Toggle navigation" aria-expanded="false"><i data-icon="menu"></i></button>
    <div class="breadcrumb"><span class="crumb-root">Astra</span><span class="crumb-sep">/</span><strong id="crumb">Overview</strong></div>
    <div class="topbar-right">
      <span class="clock-chip" title="Sri Lanka time (UTC+05:30)"><i data-icon="clock"></i><strong data-sl-clock>--:--:--</strong><small>SL</small></span>
      <span class="pill" id="connection-pill"><span class="status-dot amber"></span>Connecting</span>
      <?php if(!$isAdmin): ?><a href="login.php" class="button small readonly-pill"><i data-icon="lock"></i>Sign in</a><?php endif; ?>
      <button id="refresh" class="icon-button" aria-label="Refresh dashboard" title="Refresh"><i data-icon="refresh"></i></button>
    </div>
  </header>
  <main id="main">
    <div class="page-heading"><div><h1 id="page-title">Overview</h1><p id="page-description" class="muted">What is running now and what happens next.</p></div><button id="primary-action" class="button primary" hidden></button></div>
    <div id="notice" hidden></div>
    <div id="page-content" aria-live="polite"><div class="loading">Loading…</div></div>
    <footer class="footer"><span>Astra Video · v0.2</span><span id="last-sync">Connecting…</span></footer>
  </main>
</div>
<dialog id="modal"><div class="modal-heading"><h2 id="modal-title">New job</h2><button class="icon-button" id="modal-close" aria-label="Close dialog"><i data-icon="x"></i></button></div><form id="modal-form"><div id="modal-fields"></div><p id="modal-error" class="error" hidden></p><div class="modal-actions"><button type="button" id="modal-cancel" class="button">Cancel</button><button type="submit" id="modal-submit" class="button primary">Save</button></div></form></dialog><div id="toast" role="status" hidden></div>
</body></html>
