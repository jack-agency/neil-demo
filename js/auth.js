/* Auth — fetch wrapper + user info + logout */

const _fetch = window.fetch;
window.fetch = async function(...args) {
  const res = await _fetch.apply(this, args);
  if (res.status === 401 && !String(args[0]).includes('/auth/')) {
    window.location.href = '/login';
    throw new Error('Session expired');
  }
  return res;
};

async function loadUser() {
  try {
    const res = await fetch('/auth/me');
    if (res.ok) {
      const data = await res.json();
      document.getElementById('navUser').textContent = data.email;
    }
  } catch (e) {}
}

async function logout() {
  await fetch('/auth/logout', { method: 'POST' });
  window.location.href = '/login';
}
