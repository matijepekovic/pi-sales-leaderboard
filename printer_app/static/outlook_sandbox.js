/* Outlook trial UI: same-origin admin requests, no tokens or messages in local storage. */
(() => {
  const get = id => document.getElementById(id);
  const csrf = get('outlookCsrf').value;
  const statusNode = get('outlookConnectionStatus');
  const actionNode = get('outlookActionResult');
  const codeBox = get('outlookSignIn');
  const messagesNode = get('outlookMessages');
  const stageNode = get('outlookStageResult');

  async function request(url, values) {
    const body = new URLSearchParams({csrf, ...(values || {})});
    const response = await fetch(url, {method: 'POST', body, credentials: 'same-origin'});
    const answer = await response.json();
    if (!response.ok || !answer.ok) throw new Error(answer.message || 'Outlook sandbox request failed.');
    return answer.result;
  }

  async function status() {
    try {
      const response = await fetch('/outlook-sandbox/status', {credentials: 'same-origin'});
      const answer = await response.json();
      if (!response.ok || !answer.ok) throw new Error(answer.message || 'Could not read Outlook status.');
      const current = answer.result;
      if (current.state === 'pending') {
        statusNode.textContent = 'Sign-in pending. Complete Microsoft / Okta verification in your browser.';
      } else if (current.state === 'failed') {
        statusNode.textContent = current.message || 'Microsoft sign-in failed.';
      } else if (!current.app_ready) {
        statusNode.textContent = 'Microsoft application approval is not configured yet. Okta verification alone cannot connect Outlook.';
      } else if (current.signed_in) {
        statusNode.textContent = 'Connected as ' + (current.account || current.mailbox) + '. You can test your Outlook folder.';
      } else {
        statusNode.textContent = 'Ready to connect. Click Connect Outlook and complete your normal company sign-in.';
      }
      if (current.mailbox && get('outlookMailbox').value.trim() === '') {
        get('outlookMailbox').value = current.mailbox;
      }
      codeBox.hidden = current.state !== 'pending';
      get('outlookUserCode').textContent = current.state === 'pending' ? current.code : '';
    } catch (err) {
      statusNode.textContent = err.message;
    }
  }

  function busy(button, promise) {
    button.disabled = true;
    Promise.resolve().then(promise).catch(err => {
      actionNode.textContent = err.message || 'Outlook sandbox request failed.';
      actionNode.className = 'error';
    }).finally(() => { button.disabled = false; });
  }

  get('outlookConnect').addEventListener('click', event => busy(event.currentTarget, async () => {
    const info = await request(get('outlookConnect').dataset.url);
    actionNode.textContent = info.state === 'pending'
      ? 'Microsoft code is ready. Open the sign-in link below.'
      : 'Microsoft connection request started.';
    actionNode.className = 'muted';
    await status();
  }));

  get('outlookDisconnect').addEventListener('click', event => busy(event.currentTarget, async () => {
    await request(get('outlookDisconnect').dataset.url);
    messagesNode.replaceChildren();
    stageNode.replaceChildren();
    actionNode.textContent = 'Microsoft authorization cleared from this Printer App. Existing staged files remain private.';
    actionNode.className = 'muted';
    await status();
  }));

  get('outlookFolders').addEventListener('click', event => busy(event.currentTarget, async () => {
    const folders = await request(get('outlookFolders').dataset.url);
    const choices = get('outlookFolderNames');
    choices.replaceChildren();
    folders.forEach(name => {
      const option = document.createElement('option');
      option.value = name;
      choices.append(option);
    });
    get('outlookFolderResult').textContent = folders.length
      ? 'Available folders: ' + folders.join(', ') + '. Choose one above and Save Settings.'
      : 'No folders were returned by Outlook.';
  }));

  function resultLine(label, text) {
    const p = document.createElement('p');
    const strong = document.createElement('strong');
    strong.textContent = label;
    p.append(strong, document.createTextNode(text));
    return p;
  }

  get('outlookCheck').addEventListener('click', event => busy(event.currentTarget, async () => {
    get('outlookCheckResult').textContent = 'Checking the selected Outlook folder…';
    const scan = await request(get('outlookCheck').dataset.url);
    messagesNode.replaceChildren();
    get('outlookCheckResult').textContent = scan.messages.length
      ? 'Read-only connection succeeded: ' + scan.messages.length + ' recent message(s) in ' + scan.folder + '.'
      : 'Connected to ' + scan.folder + '. No messages found.';
    for (const message of scan.messages) {
      const article = document.createElement('article');
      article.append(resultLine('Subject: ', message.subject || '(no subject)'));
      article.append(resultLine('From: ', message.sender || 'Unknown sender'));
      article.append(resultLine('Date: ', message.date || 'Unknown date'));
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Stage attachments';
      button.addEventListener('click', () => {
        button.disabled = true;
        stageNode.textContent = 'Downloading attachments into private sandbox storage…';
        request('/outlook-sandbox/stage', {uid: message.uid}).then(record => {
          stageNode.replaceChildren();
          stageNode.append(resultLine('Staged ', record.files.length + ' attachment(s). No printing occurred.'));
          const list = document.createElement('ul');
          for (const file of record.files) {
            const li = document.createElement('li');
            const link = document.createElement('a');
            link.href = file.download_url;
            link.textContent = file.name + ' (' + file.bytes + ' bytes)';
            li.append(link);
            list.append(li);
          }
          stageNode.append(list);
        }).catch(err => {
          stageNode.textContent = err.message || 'Could not stage attachments.';
        }).finally(() => { button.disabled = false; });
      });
      article.append(button);
      messagesNode.append(article);
    }
  }));
  status();
  window.setInterval(status, 4000);
})();
