(() => {
  const $=(selector)=>document.querySelector(selector);
  const labels={dashboard:"نمای کلی",providers:"سرویس‌های هوش مصنوعی",users:"کاربران",community:"گروه‌ها و کانال‌ها",conversations:"تاریخچه مکالمات",audit:"گزارش فعالیت‌ها",payments:"پرداخت‌ها",broadcast:"پیام همگانی",prompt:"دستورالعمل دستیار",system:"تنظیمات سیستم"};
  let username="";
  async function api(path,options={}){
    const response=await fetch(path,{credentials:"same-origin",...options,headers:{"content-type":"application/json",...(options.headers||{})}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.detail||"درخواست انجام نشد.");
    return data;
  }
  function message(text,type=""){$("#message").textContent=text;$("#message").className="message"+(type?" "+type:"");}
  function showDashboard(me){
    $("#login").classList.add("hidden");$("#dashboard").classList.remove("hidden");
    $("#manager-name").textContent="حساب: "+(me.username||username)+" · نقش: مدیر ربات";
    const area=$("#permissions");area.replaceChildren();
    for(const key of me.permissions||[]){const chip=document.createElement("span");chip.className="chip";chip.textContent=labels[key]||key;area.append(chip);}
  }
  $("#pin-form").addEventListener("submit",async(event)=>{
    event.preventDefault();username=$("#username").value.trim().toLowerCase();
    const button=event.submitter;button.disabled=true;
    try{
      const result=await api("/auth/manager-login",{method:"POST",body:JSON.stringify({username,password:$("#pin").value})});
      $("#pin-form").classList.add("hidden");$("#otp-form").classList.remove("hidden");$("#otp").focus();
      message(result.message||"کد یک‌بارمصرف به تلگرام متصل به حساب ارسال شد.","success");
    }catch(error){message(error.message,"error");}
    finally{button.disabled=false;}
  });
  $("#otp-form").addEventListener("submit",async(event)=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    try{await api("/auth/manager-verify",{method:"POST",body:JSON.stringify({username,code:$("#otp").value.trim()})});const me=await api("/auth/me");showDashboard(me);}
    catch(error){message(error.message,"error");}
    finally{button.disabled=false;}
  });
  $("#back-button").addEventListener("click",()=>{$("#otp-form").classList.add("hidden");$("#pin-form").classList.remove("hidden");$("#otp").value="";message("");});
  $("#logout").addEventListener("click",async()=>{try{await api("/auth/logout",{method:"POST",body:"{}"});}finally{location.reload();}});
  api("/auth/me").then(me=>{if(me.role==="manager")showDashboard(me);}).catch(()=>{});
})();
