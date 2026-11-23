"use strict";

const chat = document.querySelector("#chat");
const welcome = document.querySelector("#welcome");
const view = document.querySelector("#view");
const form = document.querySelector("#message-form");
const input = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const waiting = document.querySelector("#waiting");
const privacy = document.querySelector("#privacy");
const errorBox = document.querySelector("#request-error");
const errorText = document.querySelector("#error-text");
const retry = document.querySelector("#retry");

const consentKey = "chat_cookie_consent";
let consent = readConsent();
let pending = false;
let failedText;
let historyRequest;
const recentTurns = [];

function rememberTurn(role, content) {
    recentTurns.push({role, content: Array.from(content).slice(0, 800).join("")});
    if (recentTurns.length > 4) recentTurns.shift();
}

function readConsent() {
    try {
        return localStorage.getItem(consentKey);
    } catch {
        return null;
    }
}

function saveConsent(value) {
    consent = value;
    try {
        localStorage.setItem(consentKey, value);
    } catch {
        // Continue with this choice for the current page.
    }
}

function webUrl(value) {
    try {
        const url = new URL(value);
        if ((url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password) {
            return url.href;
        }
    } catch {
        return null;
    }
    return null;
}

function makeLink(label, url) {
    const link = document.createElement("a");
    link.href = url;
    link.textContent = label;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
}

function appendAnswer(container, value) {
    // Chat answers use a small subset of Markdown. Build with text nodes and
    // validated links so model or document output cannot create live HTML.
    const markup = /\[([^\]\n]+)\]\(([^\s)]+)\)|\*\*([^*\n]+)\*\*|https?:\/\/[^\s<>\[\])]+/g;
    let offset = 0;
    for (const match of value.matchAll(markup)) {
        container.append(value.slice(offset, match.index));
        const [token, label, href, bold] = match;
        if (bold) {
            const strong = document.createElement("strong");
            strong.textContent = bold;
            container.append(strong);
        } else {
            const linkValue = href ?? token.replace(/[.,;!?]+$/, "");
            const url = webUrl(linkValue);
            if (url) {
                container.append(makeLink(label ?? linkValue, url));
                if (!href) container.append(token.slice(linkValue.length));
            } else {
                container.append(token);
            }
        }
        offset = match.index + token.length;
    }
    container.append(value.slice(offset));
}

function addMessage(text, sender) {
    welcome.hidden = true;
    const row = document.createElement("article");
    row.className = `message ${sender}`;

    const label = document.createElement("p");
    label.className = "message-label";
    label.textContent = sender === "user" ? "คุณ" : "ผู้ช่วยเทศบาล";

    const message = document.createElement("p");
    message.className = "bubble";
    if (sender === "user") message.textContent = text;
    else appendAnswer(message, text);

    row.append(label, message);
    if (sender === "assistant" && navigator.clipboard?.writeText) {
        const copy = document.querySelector("#copy-answer-template").content.firstElementChild.cloneNode(true);
        const copyLabel = copy.querySelector("span");
        copy.addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(text);
                copyLabel.textContent = "คัดลอกแล้ว";
            } catch {
                copyLabel.textContent = "คัดลอกไม่ได้";
            }
        });
        row.append(copy);
    }
    chat.append(row);
}

function scrollToLatest() {
    view.scrollTop = view.scrollHeight;
}

async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    const {signal, ...requestOptions} = options;
    function abort() {
        controller.abort();
    }
    signal?.addEventListener("abort", abort, {once: true});
    if (signal?.aborted) abort();
    try {
        const response = await fetch(`${window.API_BASE}${path}`, {
            credentials: "include",
            ...requestOptions,
            signal: controller.signal,
        });

        if (response.status === 429) throw new Error("กรุณารอสักครู่ก่อนส่งคำถามอีกครั้ง");
        if (!response.ok) throw new Error("ตอนนี้เชื่อมต่อผู้ช่วยเทศบาลไม่ได้ กรุณาลองอีกครั้ง");
        const data = await response.json();
        if (data?.error) throw new Error("ระบบตอบคำถามขัดข้อง กรุณาลองอีกครั้ง");
        return data;
    } finally {
        clearTimeout(timeout);
        signal?.removeEventListener("abort", abort);
    }
}

async function loadHistory() {
    const controller = new AbortController();
    historyRequest = controller;
    try {
        const data = await api("/chat/history", {signal: controller.signal});
        if (consent !== "accepted" || controller.signal.aborted) return;
        if (data.session_expired) return;
        for (const item of data.history ?? []) {
            if (typeof item.content !== "string") continue;
            addMessage(item.content, item.role === "user" ? "user" : "assistant");
        }
        scrollToLatest();
    } catch {
        // Failed history restoration does not prevent starting a new chat.
    } finally {
        if (historyRequest === controller) historyRequest = null;
    }
}

async function ask(text, isRetry = false) {
    if (pending || !text) return;

    historyRequest?.abort();
    pending = true;
    sendButton.disabled = true;
    retry.disabled = true;
    errorBox.hidden = true;
    document.querySelector("#history-notice").hidden = true;
    failedText = undefined;

    if (!isRetry) addMessage(text, "user");
    waiting.hidden = false;
    scrollToLatest();

    const noSave = consent !== "accepted";
    const payload = JSON.stringify({
        message: text,
        no_save: noSave,
        ...(noSave && recentTurns.length ? {recent: recentTurns} : {}),
    });
    const options = {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: payload,
    };
    try {
        let data = await api("/chat", options);
        // Older deployments clear an expired cookie without answering.
        if (data.session_expired && !data.answer) data = await api("/chat", options);
        if (typeof data.answer !== "string" || !data.answer.trim()) {
            throw new Error("ระบบยังส่งคำตอบกลับมาไม่ได้ กรุณาลองอีกครั้ง");
        }
        addMessage(data.answer, "assistant");
        if (data.history_saved === false) {
            const notice = document.querySelector("#history-notice");
            notice.hidden = false;
            notice.textContent = "ตอบคำถามแล้ว แต่บันทึกประวัติครั้งนี้ไม่ได้";
        }
        rememberTurn("user", text);
        rememberTurn("assistant", data.answer);
    } catch (error) {
        failedText = text;
        errorText.textContent = error.name === "AbortError"
            ? "ระบบใช้เวลาตอบนานเกินไป กรุณาลองอีกครั้ง"
            : error.message.startsWith("ระบบ") || error.message.startsWith("ตอนนี้") || error.message.startsWith("กรุณา")
                ? error.message
                : "ตอนนี้เชื่อมต่อผู้ช่วยเทศบาลไม่ได้ กรุณาลองอีกครั้ง";
        errorBox.hidden = false;
    } finally {
        waiting.hidden = true;
        pending = false;
        sendButton.disabled = false;
        retry.disabled = false;
        scrollToLatest();
    }
}

form.addEventListener("submit", event => {
    event.preventDefault();
    if (pending) return;
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    ask(text);
});

for (const button of document.querySelectorAll("[data-question]")) {
    button.addEventListener("click", () => {
        input.focus();
        ask(button.dataset.question);
    });
}

retry.addEventListener("click", () => {
    input.focus();
    ask(failedText, true);
});

document.querySelector("#open-privacy").addEventListener("click", () => {
    privacy.returnValue = "";
    privacy.showModal();
});

privacy.addEventListener("close", () => {
    const choice = privacy.returnValue;
    if (choice !== "accepted" && choice !== "declined") return;
    if (choice === consent) return;

    saveConsent(choice);
    if (choice === "declined") historyRequest?.abort();
    else if (!chat.childElementCount) loadHistory();
});

if (consent === "accepted") loadHistory();
