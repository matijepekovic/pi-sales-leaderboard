'use strict';

import {createNotesEditor} from './report_notes_editor.js';

const choices = JSON.parse(document.getElementById('report-printing-config').dataset.choices);
const numbers = JSON.parse(document.getElementById('report-printing-config').dataset.numbers);
const dialog = document.getElementById('override-dialog');
let activeId = null;
const picker = document.getElementById('search-dialog');
const folderPanel = document.getElementById('picker-folders');
const reportPanel = document.getElementById('picker-reports');
const folderResults = document.getElementById('folder-results');
const folderStatus = document.getElementById('folder-status');
const results = document.getElementById('search-results');
const searchStatus = document.getElementById('search-status');
let folders = [];
let reports = [];
let folderRequest = 0;
let reportRequest = 0;
function filterFolders() {
  folderResults.replaceChildren();
  folderStatus.textContent = folders.length + ' folders';
  for (const folder of folders) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'picker-item';
    button.textContent = '📁 ' + folder;
    button.onclick = () => openFolder(folder);
    folderResults.append(button);
  }
}
async function loadFolders() {
  const requestId = ++folderRequest;
  folderStatus.textContent = 'Loading folders…';
  folderResults.replaceChildren();
  try {
    const response = await fetch(document.getElementById('report-printing-config').dataset.foldersUrl);
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Folder lookup failed');
    if (requestId !== folderRequest) return;
    folders = data.folders;
    filterFolders();
  } catch (error) {
    if (requestId === folderRequest) folderStatus.textContent = error.message;
  }
}
function filterReports() {
  results.replaceChildren();
  searchStatus.textContent = reports.length + ' reports';
  for (const report of reports) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'picker-item';
    const added = Array.from(document.querySelectorAll('.report-row')).some(row => row.dataset.id === report.id);
    button.textContent = (added ? '✓ ' : '+ ') + report.name;
    button.disabled = added;
    button.onclick = () => { addSelectedReport(report); filterReports(); };
    results.append(button);
  }
}
async function openFolder(folder) {
  const requestId = ++reportRequest;
  folderPanel.hidden = true;
  reportPanel.hidden = false;
  document.getElementById('selected-folder').textContent = folder;
  results.replaceChildren();
  searchStatus.textContent = 'Loading reports…';
  try {
    const response = await fetch(document.getElementById('report-printing-config').dataset.reportsUrl + '?folder=' + encodeURIComponent(folder));
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Report lookup failed');
    if (requestId !== reportRequest) return;
    reports = data.reports;
    filterReports();
    if (data.total > reports.length) searchStatus.textContent += ' (first ' + reports.length + ' shown)';
  } catch (error) {
    if (requestId === reportRequest) searchStatus.textContent = error.message;
  }
}
picker.addEventListener('toggle', () => {
  if (!picker.open) return;
  ++reportRequest;
  folderPanel.hidden = false;
  reportPanel.hidden = true;
  loadFolders();
});
document.getElementById('back-to-folders').onclick = () => {
  ++reportRequest;
  reportPanel.hidden = true;
  folderPanel.hidden = false;
  filterFolders();
};
function addSelectedReport(report) {
  if (Array.from(document.querySelectorAll('.report-row')).some(row => row.dataset.id === report.id)) return;
  const row = document.createElement('div'); row.className = 'report-row'; row.dataset.id = report.id;
  const label = document.createElement('label');
  const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.name = 'report_id'; checkbox.value = report.id; checkbox.checked = true;
  label.append(checkbox, document.createTextNode(' ' + report.name + ' (' + report.id + ')'));
  const name = document.createElement('input'); name.type = 'hidden'; name.name = 'report_name_' + report.id; name.value = report.name;
  const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'edit-override'; edit.dataset.id = report.id; edit.textContent = '✎ Edit';
  const override = document.createElement('input'); override.type = 'hidden'; override.dataset.override = report.id; override.id = 'override_' + report.id; override.value = '{}';
  const notes = document.createElement('input'); notes.type = 'hidden'; notes.dataset.notes = report.id; notes.id = 'notes_' + report.id; notes.value = '{}';
  row.append(label, name, edit, override, notes); document.getElementById('report-list').append(row);
}
document.getElementById('report-list').addEventListener('click', event => {
  const button = event.target.closest('.edit-override');
  if (!button) return;
  activeId = button.dataset.id;
  const values = JSON.parse(document.getElementById('override_' + activeId).value);
  const fields = document.getElementById('override-fields');
  fields.replaceChildren();
  for (const [key, spec] of Object.entries(choices)) {
    const label = document.createElement('label');
    label.textContent = spec[1] + ' ';
    const select = document.createElement('select');
    select.dataset.key = key;
    for (const [value, name] of [['', 'Inherit job default'], ...spec[2]]) {
      const option = new Option(name, value);
      option.selected = (values[key] || '') === value;
      select.add(option);
    }
    label.append(select);
    fields.append(label);
  }
  for (const [key, spec] of Object.entries(numbers)) {
    const label = document.createElement('label');
    label.textContent = spec[1] + ' ';
    const input = document.createElement('input');
    input.type = 'number';
    input.min = spec[2]; input.max = spec[3];
    input.placeholder = 'Inherit';
    input.dataset.key = key;
    input.value = values[key] || '';
    label.append(input); fields.append(label);
  }
  notesEditor.open(activeId, JSON.parse(document.getElementById('notes_' + activeId).value));
  dialog.showModal();
});
document.getElementById('override-save').addEventListener('click', () => {
  const inputs = Array.from(dialog.querySelectorAll('[data-key]'));
  if (inputs.some(field => !field.reportValidity())) return;
  const notes = notesEditor.read();
  if (!notes) return;
  const values = {};
  inputs.forEach(field => { if (field.value !== '') values[field.dataset.key] = field.value; });
  document.getElementById('override_' + activeId).value = JSON.stringify(values);
  document.getElementById('notes_' + activeId).value = JSON.stringify(notes);
  dialog.close();
});
document.getElementById('override-cancel').addEventListener('click', () => dialog.close());
// Only submit selected report settings, respecting the application's form limit.
document.getElementById('job-form').addEventListener('submit', () => {
  document.querySelectorAll('.report-row').forEach(row => {
    const checked = row.querySelector('input[name="report_id"]').checked;
    for (const key of ['override', 'notes']) {
      const input = row.querySelector('[data-' + key + ']');
      if (checked) input.name = key + '_' + row.dataset.id;
      else input.removeAttribute('name');
    }
  });
});

function effectivePreviewOptions() {
  const values = {};
  for (const key of [...Object.keys(choices), ...Object.keys(numbers)]) {
    values[key] = document.querySelector('#job-form [name="' + key + '"]').value;
  }
  dialog.querySelectorAll('[data-key]').forEach(input => { if (input.value !== '') values[input.dataset.key] = input.value; });
  return values;
}
const notesEditor = createNotesEditor({
  dialog,
  previewUrl: document.getElementById('report-printing-config').dataset.previewUrl,
  csrf: () => document.querySelector('#job-form [name="csrf"]').value,
  effectiveOptions: effectivePreviewOptions,
});
