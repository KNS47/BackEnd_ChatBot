"use strict";

const form = document.querySelector("#login-form");
const password = document.querySelector("#password");
const toggle = document.querySelector("#toggle-password");
const errorBox = document.querySelector("#error");
const submit = document.querySelector("#submit");
const status = document.querySelector("#login-status");

try {
    sessionStorage.removeItem("admin_auth");
} catch {
    // Authentication uses the server session when browser storage is unavailable.
}

toggle.addEventListener("click", () => {
    const visible = password.type === "password";
    password.type = visible ? "text" : "password";
    toggle.setAttribute("aria-pressed", String(visible));
    toggle.querySelector("span").textContent = visible ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน";
});

form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submit.disabled) return;

    const data = new FormData(form);
    const username = data.get("username").trim();
    if (!username) {
        errorBox.textContent = "กรุณากรอกชื่อผู้ใช้";
        errorBox.hidden = false;
        form.elements.username.focus();
        return;
    }
    data.set("username", username);
    const fail = message => {
        errorBox.textContent = message;
        errorBox.hidden = false;
    };
    submit.disabled = true;
    submit.querySelector("span").textContent = "กำลังเข้าสู่ระบบ…";
    status.textContent = "กำลังเข้าสู่ระบบ…";
    errorBox.hidden = true;
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 15000);
    try {
        const response = await fetch(`${window.API_BASE}/api/login`, {
            method: "POST",
            body: data,
            credentials: "include",
            signal: abort.signal,
        });
        if (response.ok) {
            const session = await fetch(`${window.API_BASE}/api/check-admin`, {
                credentials: "include",
                signal: abort.signal,
            });
            if (session.ok && (await session.json()).authenticated) {
                password.value = "";
                window.location.replace("/admin.html");
                return;
            }
            fail("เปิดเซสชันไม่ได้ กรุณาตรวจการตั้งค่าคุกกี้ของเบราว์เซอร์แล้วลองอีกครั้ง");
        } else if (response.status === 401) {
            fail("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง");
            password.value = "";
            password.focus();
        } else if (response.status === 429) {
            fail("ลองเข้าสู่ระบบหลายครั้ง กรุณารอสักครู่แล้วลองใหม่");
        } else {
            fail("ระบบเข้าสู่ระบบขัดข้อง กรุณาลองอีกครั้ง");
        }
    } catch {
        fail("เชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง");
    } finally {
        clearTimeout(timeout);
        status.textContent = "";
        submit.querySelector("span").textContent = "เข้าสู่ระบบ";
        submit.disabled = false;
    }
});
