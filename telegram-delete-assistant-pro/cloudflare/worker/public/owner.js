(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const state = { managers: [], permissions: [
    ["dashboard","نمای کلی"],["providers","سرویس‌های هوش مصنوعی"],["users","کاربران"],
    ["community","گروه‌ها و کانال‌ها"],["conversations","تاریخچه مکالمات"],["audit","گزارش فعالیت‌ها"],
    ["payments","پرداخت‌ها"],["broadcast","پیام همگانی"],["prompt","دستورالعمل دستیار"],["system","تنظیمات سیستم"]
  ]};
  const labels = Object.fromEntries(state.permissions);
  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: { "content-type": "application/json", ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "درخواست انجام نشد.");
    return data;
  }
  function notice(node, message, kind = "") {
    node.textContent = message;
    node.className = "notice" + (kind ? " " + kind : "");
  }
  function makePermissionInputs(container, selected = ["dashboard"], name = "permissions") {
    container.replaceChildren();
    for (const [key, label] of state.permissions) {
      const wrapper = document.createElement("label");
      wrapper.className = "permission-option";
      const input = document.createElement("input");
      input.type = "checkbox"; input.name = name; input.value = key;
      input.checked = selected.includes(key);
      const text = document.createElement("span"); text.textContent = label;
      wrapper.append(input, text); container.append(wrapper);
    }
  }
  function selectedPermissions(container) {
    return [...container.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value);
  }
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function renderManagers() {
    const list = $("#manager-list"); list.replaceChildren();
    if (!state.managers.length) { list.append(el("p","muted","هنوز مدیری ثبت نشده است.")); return; }
    for (const manager of state.managers) {
      const card = el("article","manager-card");
      const head = el("div","manager-head");
      const info = el("div","");
      info.append(el("div","manager-name",manager.username),el("div","manager-meta","Telegram ID: " + (manager.telegram_user_id ?? "—") + " · ID: " + manager.id));
      head.append(info,el("span","status" + (manager.is_active ? "" : " off"),manager.is_active ? "فعال" : "غیرفعال"));
      card.append(head);
      const chips = el("div","manager-permissions");
      for (const key of manager.permissions || []) chips.append(el("span","permission-chip",labels[key] || key));
      card.append(chips);
      const actions = el("div","manager-actions");
      const edit = el("button","ghost","ویرایش دسترسی‌ها");
      edit.type="button";
      const toggle = el("button",manager.is_active ? "danger-button" : "ghost",manager.is_active ? "غیرفعال‌سازی" : "فعال‌سازی");
      toggle.type="button";
      const reset = el("button","ghost","تغییر رمز");
      reset.type="button";
      const revoke = el("button","ghost","ابطال نشست‌ها");
      revoke.type="button";
      actions.append(edit,toggle,reset,revoke); card.append(actions);
      const editArea = el("div","edit-area hidden");
      const permissions = el("div","permission-grid");
      makePermissionInputs(permissions,manager.permissions || ["dashboard"],"manager_permissions");
      const save = el("button","primary","ذخیره دسترسی‌ها"); save.type="button";
      editArea.append(permissions,save); card.append(editArea);
      edit.addEventListener("click",()=>editArea.classList.toggle("hidden"));
      save.addEventListener("click",async()=>{
        try { await api("/owner/api/managers/"+manager.id,{method:"PATCH",body:JSON.stringify({permissions:selectedPermissions(permissions)})}); notice($("#list-message"),"دسترسی‌ها ذخیره شد.","success"); await loadManagers(); }
        catch(error){notice($("#list-message"),error.message,"error");}
      });
      toggle.addEventListener("click",async()=>{
        try { await api("/owner/api/managers/"+manager.id,{method:"PATCH",body:JSON.stringify({is_active:!manager.is_active})}); notice($("#list-message"),"وضعیت مدیر تغییر کرد.","success"); await loadManagers(); }
        catch(error){notice($("#list-message"),error.message,"error");}
      });
      reset.addEventListener("click",async()=>{
        const pin=window.prompt("رمز جدید چهاررقمی را وارد کن:");
        if(pin===null)return;
        if(!/^\d{4}$/.test(pin)){notice($("#list-message"),"رمز باید دقیقاً چهار رقم باشد.","error");return;}
        try { await api("/owner/api/managers/"+manager.id,{method:"PATCH",body:JSON.stringify({password:pin})}); notice($("#list-message"),"رمز تغییر کرد و نشست‌های قبلی نامعتبر شدند.","success"); await loadManagers(); }
        catch(error){notice($("#list-message"),error.message,"error");}
      });
      revoke.addEventListener("click",async()=>{
        if(!window.confirm("تمام نشست‌های این مدیر باطل شود؟"))return;
        try { await api("/owner/api/managers/"+manager.id+"/revoke",{method:"POST",body:"{}"}); notice($("#list-message"),"تمام نشست‌های مدیر باطل شدند.","success"); }
        catch(error){notice($("#list-message"),error.message,"error");}
      });
      list.append(card);
    }
  }
  async function loadManagers() {
    const result=await api("/owner/api/managers");
    state.managers=result.managers||[];
    $("#total-count").textContent=state.managers.length.toLocaleString("fa-IR");
    $("#active-count").textContent=state.managers.filter(x=>x.is_active).length.toLocaleString("fa-IR");
    $("#inactive-count").textContent=state.managers.filter(x=>!x.is_active).length.toLocaleString("fa-IR");
    renderManagers();
  }
  async function showApp() {
    $("#login-view").classList.add("hidden"); $("#app-view").classList.remove("hidden");
    await loadManagers();
  }
  $("#request-code-form").addEventListener("submit",async(event)=>{
    event.preventDefault();
    const button=event.submitter; button.disabled=true;
    try { await api("/auth/owner-request-code",{method:"POST",body:"{}"}); $("#login-form").classList.remove("hidden"); notice($("#login-message"),"کد ورود به تلگرام مالک ارسال شد.","success"); $("#owner-code").focus(); }
    catch(error){notice($("#login-message"),error.message,"error");}
    finally{button.disabled=false;}
  });
  $("#login-form").addEventListener("submit",async(event)=>{
    event.preventDefault();
    try { await api("/auth/owner-login",{method:"POST",body:JSON.stringify({code:$("#owner-code").value.trim()})}); await showApp(); }
    catch(error){notice($("#login-message"),error.message,"error");}
  });
  $("#create-manager-form").addEventListener("submit",async(event)=>{
    event.preventDefault();
    const form=event.currentTarget;
    const data=new FormData(form);
    const payload={username:data.get("username"),telegram_user_id:data.get("telegram_user_id"),password:data.get("password"),permissions:selectedPermissions($("#new-permissions"))};
    try {
      const result=await api("/owner/api/managers",{method:"POST",body:JSON.stringify(payload)});
      notice($("#create-message"),result.notification_sent ? "مدیر ساخته شد و پیام اطلاعات حساب به تلگرام او ارسال شد." : "مدیر ساخته شد، اما ارسال پیام تلگرام تأیید نشد.","success");
      form.reset(); makePermissionInputs($("#new-permissions"),["dashboard","community"]);
      await loadManagers();
    } catch(error){notice($("#create-message"),error.message,"error");}
  });
  $("#refresh-button").addEventListener("click",async()=>{try{await loadManagers();notice($("#list-message"),"فهرست به‌روزرسانی شد.","success");}catch(error){notice($("#list-message"),error.message,"error");}});
  $("#logout-button").addEventListener("click",async()=>{try{await api("/auth/logout",{method:"POST",body:"{}"});}finally{location.reload();}});
  makePermissionInputs($("#new-permissions"),["dashboard","community"]);
  api("/auth/me").then((me)=>{if(me.role==="owner")return showApp();}).catch(()=>{});
})();
