/**
 * Publishes Google Tasks and Google Contacts birthdays as JSON for the Kindle
 * calendar generator.
 *
 * Google gives no iCal feed for Tasks, and the auto "Birthdays" calendar has no
 * secret iCal address, so this script exposes both under one secret URL.
 *
 * Setup (once):
 *  1. https://script.google.com  ->  New project
 *  2. Paste this file over Code.gs
 *  3. Services (+)  ->  add "Tasks API" and "People API" (default identifiers
 *     Tasks / People)
 *  4. Edit SHARED_SECRET below to a long random string
 *  5. Deploy  ->  New deployment  ->  Web app
 *       Execute as: Me
 *       Who has access: Anyone
 *  6. Authorize when prompted, then copy the /exec URL
 *  7. Store it as the GitHub secret EXTRAS_URL, with the token appended:
 *       https://script.google.com/macros/s/DEPLOY_ID/exec?token=YOUR_SECRET
 *
 * "Anyone" only means unauthenticated; the token is what keeps it private.
 * Redeploy (Manage deployments -> Edit -> Deploy) after changing this file.
 */

var SHARED_SECRET = 'CHANGE_ME_TO_A_LONG_RANDOM_STRING';

// How far ahead to report birthdays.
var BIRTHDAY_DAYS_AHEAD = 45;

// Skip tasks due further out than this. 0 disables the limit.
// Tasks with no due date are never reported.
var TASK_DAYS_AHEAD = 30;

function doGet(e) {
  var token = (e && e.parameter && e.parameter.token) || '';
  if (SHARED_SECRET === 'CHANGE_ME_TO_A_LONG_RANDOM_STRING') {
    return json({ error: 'Set SHARED_SECRET in the Apps Script project' }, 500);
  }
  if (token !== SHARED_SECRET) {
    return json({ error: 'forbidden' }, 403);
  }

  var payload = { generated: new Date().toISOString(), tasks: [], birthdays: [] };

  try {
    payload.tasks = collectTasks();
  } catch (err) {
    payload.tasksError = String(err);
  }

  try {
    payload.birthdays = collectBirthdays();
  } catch (err) {
    payload.birthdaysError = String(err);
  }

  return json(payload, 200);
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}

function collectTasks() {
  var out = [];
  var lists = Tasks.Tasklists.list({ maxResults: 100 }).items || [];
  var cutoff = null;
  if (TASK_DAYS_AHEAD > 0) {
    cutoff = new Date();
    cutoff.setDate(cutoff.getDate() + TASK_DAYS_AHEAD);
  }

  lists.forEach(function (list) {
    var tasks =
      Tasks.Tasks.list(list.id, {
        showCompleted: false,
        showHidden: false,
        maxResults: 100,
      }).items || [];

    tasks.forEach(function (t) {
      if (t.status === 'completed' || !t.title) {
        return;
      }
      // Tasks store due as a date at midnight UTC; keep only the date part.
      var due = t.due ? t.due.substring(0, 10) : '';
      if (!due) {
        return; // only tasks with a date, whether upcoming or overdue
      }
      if (cutoff && new Date(due + 'T00:00:00Z') > cutoff) {
        return;
      }
      out.push({
        title: t.title,
        due: due,
        notes: t.notes || '',
        list: list.title || '',
      });
    });
  });

  // Soonest first, so overdue tasks head the list.
  out.sort(function (a, b) {
    return a.due < b.due ? -1 : a.due > b.due ? 1 : 0;
  });
  return out;
}

function collectBirthdays() {
  var out = [];
  var pageToken = null;
  var today = new Date();
  var horizon = new Date();
  horizon.setDate(horizon.getDate() + BIRTHDAY_DAYS_AHEAD);

  do {
    var resp = People.People.Connections.list('people/me', {
      personFields: 'names,birthdays',
      pageSize: 1000,
      pageToken: pageToken,
    });
    (resp.connections || []).forEach(function (person) {
      var name =
        person.names && person.names.length ? person.names[0].displayName : '';
      var bdays = person.birthdays || [];
      if (!name || !bdays.length) {
        return;
      }
      var d = bdays[0].date;
      if (!d || !d.month || !d.day) {
        return;
      }
      // Birthdays repeat yearly, so resolve this year's (or next year's) date.
      var occurrence = new Date(today.getFullYear(), d.month - 1, d.day);
      if (occurrence < stripTime(today)) {
        occurrence = new Date(today.getFullYear() + 1, d.month - 1, d.day);
      }
      if (occurrence > horizon) {
        return;
      }
      out.push({
        name: name,
        date: Utilities.formatDate(occurrence, 'UTC', 'yyyy-MM-dd'),
        year: d.year || 0,
      });
    });
    pageToken = resp.nextPageToken;
  } while (pageToken);

  out.sort(function (a, b) {
    return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
  });
  return out;
}

function stripTime(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Run manually from the editor to check output and trigger authorization. */
function testCollect() {
  Logger.log(JSON.stringify({ tasks: collectTasks(), birthdays: collectBirthdays() }, null, 2));
}
