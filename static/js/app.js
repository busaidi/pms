const openButton = document.querySelector("[data-sidebar-open]");
const closeTargets = document.querySelectorAll("[data-sidebar-close]");

function setSidebar(open) {
  document.body.classList.toggle("sidebar-open", open);
  openButton?.setAttribute("aria-expanded", String(open));
}

openButton?.addEventListener("click", () => setSidebar(true));
closeTargets.forEach((target) => target.addEventListener("click", () => setSidebar(false)));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setSidebar(false);
});

const userMenu = document.querySelector("[data-user-menu]");
const userMenuTrigger = userMenu?.querySelector("[data-user-menu-trigger]");
const userMenuPanel = userMenu?.querySelector("[data-user-menu-panel]");

function setUserMenu(open, restoreFocus = false) {
  if (!userMenuTrigger || !userMenuPanel) return;
  userMenuTrigger.setAttribute("aria-expanded", String(open));
  userMenuPanel.hidden = !open;
  if (restoreFocus) userMenuTrigger.focus();
}

userMenuTrigger?.addEventListener("click", () => {
  setUserMenu(userMenuTrigger.getAttribute("aria-expanded") !== "true");
});
document.addEventListener("click", (event) => {
  if (userMenu && !userMenu.contains(event.target)) setUserMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && userMenuTrigger?.getAttribute("aria-expanded") === "true") {
    setUserMenu(false, true);
  }
});

function csrfToken() {
  return document.cookie.split("; ").find((row) => row.startsWith("csrftoken="))?.split("=")[1] || document.querySelector("[name=csrfmiddlewaretoken]")?.value;
}

function decode(value) {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((value.length + 3) % 4);
  return Uint8Array.from(atob(base64), (character) => character.charCodeAt(0));
}

function encode(value) {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function credentialJSON(credential) {
  const response = { clientDataJSON: encode(credential.response.clientDataJSON) };
  if (credential.response.attestationObject) response.attestationObject = encode(credential.response.attestationObject);
  if (credential.response.authenticatorData) response.authenticatorData = encode(credential.response.authenticatorData);
  if (credential.response.signature) response.signature = encode(credential.response.signature);
  if (credential.response.userHandle) response.userHandle = encode(credential.response.userHandle);
  if (credential.response.getTransports) response.transports = credential.response.getTransports();
  return { id: credential.id, rawId: encode(credential.rawId), type: credential.type, response, clientExtensionResults: credential.getClientExtensionResults(), authenticatorAttachment: credential.authenticatorAttachment };
}

async function postJSON(url, body = {}) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The security request failed.");
  return data;
}

document.querySelector("[data-passkey-register]")?.addEventListener("click", async (event) => {
  const output = document.querySelector(".passkey-message");
  try {
    const options = await postJSON(window.passkeyConfig.registerOptions);
    options.challenge = decode(options.challenge);
    options.user.id = decode(options.user.id);
    options.excludeCredentials = (options.excludeCredentials || []).map((item) => ({ ...item, id: decode(item.id) }));
    const credential = await navigator.credentials.create({ publicKey: options });
    await postJSON(window.passkeyConfig.registerVerify, { name: "My passkey", credential: credentialJSON(credential) });
    output.textContent = "Passkey registered. Reloading…";
    window.location.reload();
  } catch (error) { output.textContent = error.message; }
});

document.querySelector("[data-passkey-login]")?.addEventListener("click", async () => {
  const output = document.querySelector(".passkey-message");
  try {
    const username = document.querySelector("#id_username").value;
    if (!username) throw new Error("Enter your username first.");
    const options = await postJSON(window.passkeyConfig.authOptions, { username });
    options.challenge = decode(options.challenge);
    options.allowCredentials = (options.allowCredentials || []).map((item) => ({ ...item, id: decode(item.id) }));
    const credential = await navigator.credentials.get({ publicKey: options });
    const result = await postJSON(window.passkeyConfig.authVerify, { credential: credentialJSON(credential) });
    window.location.assign(result.redirect);
  } catch (error) { output.textContent = error.message; }
});
