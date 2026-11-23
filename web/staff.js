"use strict";

try {
    sessionStorage.removeItem("admin_auth");
} catch {
    // Authentication uses the server session.
}

const staffMenu = document.querySelector("[aria-controls='sidebar']");
staffMenu.addEventListener("click", () => {
    const open = document.getElementById("sidebar").classList.toggle("mobile-open");
    staffMenu.setAttribute("aria-expanded", String(open));
    if (open) refreshStaffUsage();
});

async function staffFetch(path, options = {}) {
    const response = await fetch(`${window.API_BASE}${path}`, {
        credentials: "include",
        signal: AbortSignal.timeout(20000),
        ...options,
    });
    if (response.status === 401) window.location.replace("/login.html");
    if (!response.ok) throw new Error(`Staff API HTTP ${response.status}`);
    return response;
}

const usage = document.createElement("section");
usage.className = "staff-usage";
usage.setAttribute("aria-labelledby", "staff-usage-title");
usage.innerHTML = `
    <div class="usage-heading">
        <h2 id="staff-usage-title">การใช้งานระบบ</h2>
        <button type="button" class="usage-refresh">อัปเดต</button>
    </div>
    <p class="usage-status" role="status"></p>
    <dl class="usage-values"></dl>
    <p class="usage-note">ค่าที่ตั้งไว้ใช้วางแผนการใช้งาน</p>
`;
document.getElementById("sidebar").append(usage);
const usageStatus = usage.querySelector(".usage-status");
const usageValues = usage.querySelector(".usage-values");
const usageRefresh = usage.querySelector(".usage-refresh");
const formatQuantity = new Intl.NumberFormat("th-TH", {maximumFractionDigits: 1});

function isQuantity(value) {
    return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function formatBytes(value) {
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit++;
    }
    return `${formatQuantity.format(value)} ${units[unit]}`;
}

function showUsageRow(label, value, limit, format) {
    const item = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    const used = isQuantity(value);
    const capped = isQuantity(limit);
    detail.textContent = used ? format(value) : "ยังไม่มีข้อมูล";
    if (capped) detail.append(` / ${format(limit)}`);
    item.append(term, detail);
    if (used && capped && limit > 0) {
        const meter = document.createElement("meter");
        meter.max = limit;
        meter.value = Math.min(value, limit);
        meter.setAttribute("aria-label", label);
        detail.append(meter);
    }
    usageValues.append(item);
}

async function refreshStaffUsage() {
    if (usageRefresh.disabled) return;
    usageRefresh.disabled = true;
    usageStatus.textContent = "กำลังโหลดการใช้งาน…";
    try {
        const response = await staffFetch("/api/admin/usage");
        const {today, limits, storage, durable} = await response.json();
        usageValues.replaceChildren();
        showUsageRow("คำถามวันนี้", today?.questions, limits?.questions, value => formatQuantity.format(value));
        showUsageRow("โทเค็นสร้างคำตอบวันนี้", today?.tokens, limits?.tokens, value => formatQuantity.format(value));
        showUsageRow("พื้นที่เก็บไฟล์ PDF", storage?.used_bytes, limits?.storage_bytes, formatBytes);
        usageStatus.textContent = durable === false ? "ยอดวันนี้อาจไม่ครบหลังระบบเริ่มใหม่" : "";
    } catch {
        usageValues.replaceChildren();
        usageStatus.textContent = "โหลดการใช้งานไม่สำเร็จ กดอัปเดตเพื่อลองใหม่";
    } finally {
        usageRefresh.disabled = false;
    }
}

usageRefresh.addEventListener("click", refreshStaffUsage);
refreshStaffUsage();

const signOut = document.getElementById("sign-out");
signOut.addEventListener("click", async () => {
    const status = document.getElementById("staff-status");
    signOut.disabled = true;
    status.textContent = "กำลังออกจากระบบ…";
    try {
        await staffFetch("/api/logout", {method: "POST"});
        window.location.replace("/login.html");
    } catch {
        status.textContent = "ออกจากระบบไม่สำเร็จ กรุณาลองอีกครั้ง";
        signOut.disabled = false;
    }
});
