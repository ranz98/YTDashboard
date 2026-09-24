document.querySelector('#save').addEventListener('click', async () => {
  const token = document.querySelector('#token').value.trim();
  const status = document.querySelector('#status');
  if (!/^[a-f0-9]{64}$/.test(token)) { status.textContent = 'Enter the 64-character pairing key.'; return; }
  await chrome.storage.local.set({token});
  await chrome.runtime.sendMessage({wake: true});
  status.textContent = 'Pairing key saved. Start the Windows runner, then check the dashboard.';
  document.querySelector('#token').value = '';
});
