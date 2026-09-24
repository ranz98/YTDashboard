<?php
// Send the main address to the public dashboard.
header('Cache-Control: no-store');
header('Location: /astra/', true, 302);
exit;
