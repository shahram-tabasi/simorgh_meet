'use strict';

const storageKey = 'simorgh-meet-recent';
const roomPath = '/simorgh/room.html';
const roomPattern = /^[a-z0-9][a-z0-9_-]{0,99}$/i;

function meetingCode(value) {
  const input = value.trim();
  if (roomPattern.test(input)) return input.toLowerCase();
  try {
    const url = new URL(input, location.origin);
    if (url.origin !== location.origin) return null;
    const code = url.pathname === roomPath
      ? url.searchParams.get('room')
      : decodeURIComponent(url.pathname.replace(/^\/|\/$/g, ''));
    return code && roomPattern.test(code) ? code.toLowerCase() : null;
  } catch {
    return null;
  }
}

function recentMeetings() {
  try {
    const entries = JSON.parse(localStorage.getItem(storageKey));
    return Array.isArray(entries)
      ? entries.filter(code => typeof code === 'string' && roomPattern.test(code)).slice(0, 5)
      : [];
  } catch {
    return [];
  }
}

function meetingUrl(code) {
  return roomPath + '?room=' + encodeURIComponent(code);
}

const joinForm = document.getElementById('join-form');
if (joinForm) {
  joinForm.addEventListener('submit', event => {
    event.preventDefault();
    const code = meetingCode(document.getElementById('meeting').value);
    if (code) location.assign(meetingUrl(code));
    else document.getElementById('join-error').textContent = 'کد جلسه یا لینک معتبر همین سرور را وارد کنید.';
  });

  document.getElementById('create').addEventListener('click', () => {
    location.assign(meetingUrl('meet-' + crypto.randomUUID()));
  });

  for (const code of recentMeetings()) {
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.href = meetingUrl(code);
    const title = document.createElement('bdi');
    title.textContent = code;
    const action = document.createElement('span');
    action.textContent = 'پیوستن';
    link.append(title, action);
    item.append(link);
    document.getElementById('recent-list').append(item);
    document.getElementById('empty-recent').hidden = true;
  }
}

const conference = document.getElementById('conference');
if (conference) {
  const code = new URL(location.href).searchParams.get('room');
  const status = document.getElementById('room-status');
  if (!code || !roomPattern.test(code)) {
    status.textContent = 'کد جلسه معتبر نیست. از صفحهٔ اصلی وارد شوید.';
  } else if (typeof JitsiMeetExternalAPI !== 'function') {
    status.textContent = 'بارگذاری سرویس جلسه ناموفق بود. صفحه را دوباره باز کنید.';
  } else {
    const copy = document.getElementById('copy-invite');
    const background = document.getElementById('background');
    const api = new JitsiMeetExternalAPI(location.host, {
      roomName: code,
      parentNode: conference,
      lang: 'fa',
      width: '100%',
      height: '100%'
    });
    api.getIFrame().title = 'تماس سیمرغ میت';
    copy.disabled = false;
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(new URL(meetingUrl(code), location.origin).href);
        status.textContent = 'لینک دعوت کپی شد.';
      } catch {
        status.textContent = 'برای دعوت، آدرس همین صفحه را از نوار مرورگر کپی کنید.';
      }
    });
    api.addListener('videoConferenceJoined', () => {
      background.disabled = false;
      status.textContent = 'برای تغییر پس‌زمینه، دوربین را روشن کنید.';
      try {
        const recent = [code, ...recentMeetings().filter(entry => entry !== code)].slice(0, 5);
        localStorage.setItem(storageKey, JSON.stringify(recent));
      } catch {
        // Storage may be disabled by browser policy.
      }
    });
    background.addEventListener('click', () => api.executeCommand('toggleVirtualBackgroundDialog'));
    api.addListener('readyToClose', () => {
      api.dispose();
      conference.hidden = true;
      status.hidden = true;
      copy.disabled = true;
      background.disabled = true;
      document.getElementById('room-archive').href = '/simorgh-archive/' + encodeURIComponent(code) + '/';
      document.getElementById('after-meeting').hidden = false;
    });
  }
}
