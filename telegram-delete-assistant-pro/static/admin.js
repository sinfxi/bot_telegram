
let data=null;const $=id=>document.getElementById(id);const labels={openrouter:'OpenRouter'};
const permissionNames={dashboard:'نمای کلی',providers:'سرویس‌های هوش مصنوعی',users:'کاربران',admins:'مدیریت ادمین‌ها',community:'گروه‌ها و کانال‌ها',conversations:'تاریخچه مکالمات',audit:'گزارش فعالیت‌ها',payments:'بررسی پرداخت‌ها',broadcast:'پیام همگانی',prompt:'دستورالعمل دستیار',system:'سلامت و تنظیمات'};
let featureDraft={};
const currentPermissions=new Set((document.querySelector('meta[name="fxi-permissions"]')?.content||'dashboard').split(',').filter(Boolean));
let editingAdminId=null;
function applyPermissions(){if($('providerOverviewCard'))$('providerOverviewCard').hidden=!currentPermissions.has('providers');if($('communityOverviewCard'))$('communityOverviewCard').hidden=!currentPermissions.has('community');document.querySelectorAll('.nav button[data-page]').forEach(b=>{const key=b.dataset.page==='overview'?'dashboard':b.dataset.page;if(!currentPermissions.has(key)&&!(key==='features'&&currentPermissions.has('system'))&&!(key==='users'&&(currentPermissions.has('admins')||currentPermissions.has('users'))))b.hidden=true});document.querySelectorAll('[data-page-permission]').forEach(el=>{el.hidden=!(currentPermissions.has(el.dataset.pagePermission)||(el.dataset.pagePermission==='users'&&currentPermissions.has('admins')))});document.querySelectorAll('[data-area-permission]').forEach(el=>{el.hidden=!currentPermissions.has(el.dataset.areaPermission)});document.querySelectorAll('[data-required-permission]').forEach(el=>{el.hidden=!currentPermissions.has(el.dataset.requiredPermission)});}

async function api(path,method='GET',body){
const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
try{
const r=await fetch('/admin/api/'+path,{method,credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json',...(body?{'Content-Type':'application/json'}:{})},body:body!==undefined?JSON.stringify(body):undefined,signal:controller.signal});
let d={};try{d=await r.json()}catch{}
if(!r.ok)throw Error(d.detail||d.message||('خطای سرور ('+r.status+')'));
return d;
}catch(e){if(e.name==='AbortError')throw Error('پاسخ سرور بیش از ۲۰ ثانیه طول کشید؛ دوباره تلاش کن.');throw e}
finally{clearTimeout(timer)}
}
let activeConversation=null;let conversationItems=[];let userItems=[];let communityItems=[];
const panelRole=document.querySelector('meta[name="fxi-panel-role"]')?.content||'manager';
const identityTitle=document.getElementById('panelIdentityTitle');
const identitySubtitle=document.getElementById('panelIdentitySubtitle');
const identityIcon=document.getElementById('panelIdentityIcon');
const panelUser=document.querySelector('meta[name="fxi-panel-user"]')?.content||'';
if(panelRole==='owner'){
if(identityTitle)identityTitle.textContent='پنل اختصاصی مالک';
if(identitySubtitle)identitySubtitle.textContent='👑 مالک اصلی'+(panelUser?' · '+panelUser:'')+' · دسترسی کامل و غیرقابل واگذاری';
if(identityIcon)identityIcon.textContent='👑';
document.body.classList.add('owner-panel');
const ownerLink=document.getElementById('ownerPanelShortcut');if(ownerLink)ownerLink.hidden=false;
}else{
if(identityTitle)identityTitle.textContent='پنل مدیر اجرایی';
if(identitySubtitle)identitySubtitle.textContent='🛡 حساب: '+(panelUser||'مدیر')+' · دسترسی فقط بر اساس مجوز مالک';
if(identityIcon)identityIcon.textContent='🛡';
document.body.classList.add('manager-panel');
}
function goPage(name){const button=document.querySelector('.nav button[data-page="'+name+'"]');if(button)button.click()}
function safeText(v){return String(v??'')}
function formatWhen(v){if(!v)return '';try{return new Date(v).toLocaleString('fa-IR',{dateStyle:'short',timeStyle:'short'})}catch{return ''}}
async function loadConversationsRequest(){try{const d=await api('conversations');conversationItems=d.items||[];renderConversations();}catch(e){note('دریافت مکالمات ناموفق بود: '+e.message)}}
function renderConversations(){const box=$('conversationList');box.innerHTML='';const q=($('conversationSearch')?.value||'').trim().toLocaleLowerCase('fa');const items=conversationItems.filter(item=>String(item.user_id).includes(q)||(item.preview||'').toLocaleLowerCase('fa').includes(q));if(!items.length){box.innerHTML='<div class="empty">موردی با این جست‌وجو پیدا نشد.</div>';return}items.forEach(item=>{const b=document.createElement('button');b.className='conv-item'+(activeConversation===item.user_id?' active':'');const title=document.createElement('b');title.textContent='کاربر تلگرام · '+item.user_id;const sub=document.createElement('small');sub.textContent=item.message_count+' پیام · '+formatWhen(item.last_message)+'\n'+item.preview;b.append(title,sub);b.onclick=()=>openConversation(item.user_id);box.appendChild(b)})}
function filterConversations(){renderConversations()}
async function openConversation(userId){activeConversation=userId;$('conversationTitle').textContent='مکالمه کاربر '+userId;$('conversationMeta').textContent='در حال بارگذاری…';$('conversationThread').textContent='در حال بازیابی پیام‌ها…';try{const d=await api('conversations/'+userId);const box=$('conversationThread');box.innerHTML='';$('conversationMeta').textContent=d.messages.length+' پیام';if(!d.messages.length){box.textContent='پیامی برای این کاربر ثبت نشده است.';return}d.messages.forEach(m=>{const el=document.createElement('div');el.className='conv-msg '+(m.role==='user'?'user':'assistant');const tag=document.createElement('small');tag.textContent=(m.role==='user'?'کاربر':'دستیار')+' · '+(labels[m.provider_id]||m.provider_id)+' · '+formatWhen(m.created_at);const body=document.createElement('div');body.textContent=m.content;el.append(tag,body);box.appendChild(el)});box.scrollTop=box.scrollHeight;loadConversations()}catch(e){$('conversationThread').textContent=e.message;$('conversationMeta').textContent='خطا'}}
function note(t){$('notice').textContent=t}
let autoRefreshEnabled=true;
let refreshInProgress=false;
let autoRefreshTimer=setInterval(()=>{if(autoRefreshEnabled&&!document.hidden)refresh()},60000);
function toggleAutoRefresh(){autoRefreshEnabled=!autoRefreshEnabled;$('autoRefreshBtn').textContent='⏱ به‌روزرسانی خودکار: '+(autoRefreshEnabled?'روشن':'خاموش');note(autoRefreshEnabled?'به‌روزرسانی خودکار هر ۶۰ ثانیه فعال است.':'به‌روزرسانی خودکار متوقف شد.');if(autoRefreshEnabled)refresh()}
const auditLabels={admin_added:'افزودن مدیر',admin_removed:'حذف مدیر',bot_enabled:'روشن‌کردن ربات',bot_disabled:'خاموش‌کردن ربات',broadcast_started:'شروع پیام همگانی',broadcast_finished:'پایان پیام همگانی',system_prompt_updated:'تغییر دستورالعمل',payment_approve:'تأیید درخواست',payment_reject:'رد درخواست',community_settings_updated:'تغییر تنظیمات گروه/کانال',telegram_user_blocked:'مسدودسازی کاربر',telegram_user_unblocked:'فعال‌سازی کاربر'};
async function loadAuditRequest(){try{const d=await api('audit');const box=$('auditList');box.innerHTML='';if(!d.items.length){box.innerHTML='<div class="empty">هنوز رویدادی ثبت نشده است.</div>';return}d.items.forEach(item=>{const el=document.createElement('div');el.className='listitem';const info=document.createElement('div');const title=document.createElement('b');title.textContent=auditLabels[item.action]||item.action;const meta=document.createElement('small');meta.className='muted';meta.textContent=formatWhen(item.at)+' · '+(item.details||'بدون جزئیات');info.append(title,meta);el.append(info);box.append(el)})}catch(e){$('auditList').textContent=e.message;note(e.message)}}
async function loadCommunityRequest(){try{const d=await api('community');communityItems=d.items||[];renderCommunity()}catch(e){note('دریافت گروه‌ها و کانال‌ها ناموفق بود: '+e.message)}}
function renderCommunity(){const box=$('communityList');if(!box)return;box.replaceChildren();const q=($('communitySearch')?.value||'').trim().toLocaleLowerCase('fa');const items=communityItems.filter(x=>String(x.chat_id).includes(q)||String(x.title||'').toLocaleLowerCase('fa').includes(q));$('communityCount').textContent=items.length+' از '+communityItems.length+' فضا';if(!items.length){box.innerHTML='<div class="empty">فضایی با این جست‌وجو پیدا نشد.</div>';return}items.forEach(x=>{const el=document.createElement('div');el.className='community-item';const info=document.createElement('div');info.className='community-info';const title=document.createElement('b');title.textContent=(x.type==='channel'?'📣 ':'👥 ')+(x.title||x.chat_id);const meta=document.createElement('small');meta.className='muted';meta.textContent='شناسه: '+x.chat_id+' · '+x.type+' · '+Number(x.message_count||0).toLocaleString('fa-IR')+' پیام · '+Number(x.members_seen||0).toLocaleString('fa-IR')+' عضو مشاهده‌شده';info.append(title,meta);el.append(info);const controls=document.createElement('div');controls.className='community-controls';const toggles=[['bot_enabled','فعالیت ربات',x.bot_enabled!==false]];if(['group','supergroup'].includes(x.type))toggles.push(['ai_enabled','پاسخ هوشمند',x.ai_enabled],['conversational_ai','گفت‌وگوی رفاقتی',x.conversational_ai],['welcome_enabled','خوشامدگویی',x.welcome_enabled],['anti_flood_enabled','ضداسپم و محدودسازی تکرار',x.anti_flood_enabled],['link_guard_enabled','کنترل لینک',x.link_guard_enabled],['keyword_filter_enabled','فیلتر کلمات',x.keyword_filter_enabled],['media_guard_enabled','محدودیت رسانه',x.media_guard_enabled]);for(const [key,label,checked] of toggles){const wrap=document.createElement('label');wrap.className='community-toggle';const input=document.createElement('input');input.type='checkbox';input.checked=Boolean(checked);input.setAttribute('aria-label',label+' '+(x.title||x.chat_id));input.addEventListener('change',()=>saveCommunitySetting(x.chat_id,key,input.checked,input));const caption=document.createElement('span');caption.textContent=label;wrap.append(input,caption);controls.append(wrap)}el.append(controls);
if(['group','supergroup'].includes(x.type)){
const presets=document.createElement('div');presets.className='community-presets';
[['balanced','متعادل','secondary'],['strict','سخت‌گیرانه','danger'],['relaxed','آزادتر','secondary']].forEach(([mode,label,cls])=>{const b=document.createElement('button');b.type='button';b.className='btn '+cls+(mode==='strict'?' strict':mode==='relaxed'?' relaxed':'');b.textContent='⚙ '+label;b.addEventListener('click',()=>saveCommunityPreset(x.chat_id,mode,b));presets.append(b)});el.append(presets);
const advanced=document.createElement('div');advanced.className='community-advanced';
const warnLabel=document.createElement('label');warnLabel.className='community-config-field';warnLabel.textContent='سقف اخطار';
const warnInput=document.createElement('input');warnInput.type='number';warnInput.min='2';warnInput.max='5';warnInput.value=String(x.warn_limit||3);warnInput.className='field';warnInput.setAttribute('aria-label','سقف اخطار '+(x.title||x.chat_id));warnLabel.append(warnInput);
const floodLabel=document.createElement('label');floodLabel.className='community-config-field';floodLabel.textContent='حد پیام در بازه ۳۰ ثانیه (ضداسپم)';const floodInput=document.createElement('input');floodInput.type='number';floodInput.min='3';floodInput.max='20';floodInput.value=String(x.flood_limit||7);floodInput.className='field';floodInput.setAttribute('aria-label','حد پیام ضداسپم '+(x.title||x.chat_id));floodLabel.append(floodInput);
const welcomeLabel=document.createElement('label');welcomeLabel.className='community-config-field words-field';welcomeLabel.textContent='متن خوشامدگویی (متغیرها: {name} و {group})';const welcomeInput=document.createElement('textarea');welcomeInput.className='field';welcomeInput.rows=2;welcomeInput.maxLength=500;welcomeInput.value=x.welcome_message||'';welcomeInput.placeholder='👋 خوش اومدی {name} به {group}!';welcomeInput.setAttribute('aria-label','متن خوشامدگویی '+(x.title||x.chat_id));welcomeLabel.append(welcomeInput);
const wordsLabel=document.createElement('label');wordsLabel.className='community-config-field words-field';wordsLabel.textContent='واژه‌های فیلتر (هر واژه در یک خط یا جداشده با ویرگول)';
const wordsInput=document.createElement('textarea');wordsInput.className='field';wordsInput.rows=2;wordsInput.value=(x.blocked_words||[]).join('\n');wordsInput.placeholder='تبلیغ\nاسپم';wordsInput.setAttribute('aria-label','واژه‌های فیلتر '+(x.title||x.chat_id));wordsLabel.append(wordsInput);
const save=document.createElement('button');save.type='button';save.className='btn secondary';save.textContent='ذخیره تنظیمات پیشرفته';save.addEventListener('click',()=>saveCommunityAdvanced(x.chat_id,warnInput,floodInput,welcomeInput,wordsInput,save));
advanced.append(warnLabel,floodLabel,welcomeLabel,wordsLabel,save);el.append(advanced);
}
box.append(el)})}
async function saveCommunityPreset(chatId,mode,button){
const presets={
balanced:{settings:{bot_enabled:true,ai_enabled:false,conversational_ai:false,welcome_enabled:true,anti_flood_enabled:true,link_guard_enabled:false,keyword_filter_enabled:false,media_guard_enabled:false},warn_limit:3,flood_limit:7},
strict:{settings:{bot_enabled:true,ai_enabled:false,conversational_ai:false,welcome_enabled:true,anti_flood_enabled:true,link_guard_enabled:true,keyword_filter_enabled:true,media_guard_enabled:true},warn_limit:2,flood_limit:5},
relaxed:{settings:{bot_enabled:true,ai_enabled:false,conversational_ai:false,welcome_enabled:true,anti_flood_enabled:false,link_guard_enabled:false,keyword_filter_enabled:false,media_guard_enabled:false},warn_limit:5,flood_limit:12}
};
const preset=presets[mode];if(!preset)return;
const labels={balanced:'متعادل',strict:'سخت‌گیرانه',relaxed:'آزادتر'};
if(!confirm('تنظیمات گروه با الگوی «'+labels[mode]+'» جایگزین شود؟'))return;
button.disabled=true;const old=button.textContent;button.textContent='در حال اعمال…';
try{const d=await api('community/'+encodeURIComponent(chatId)+'/settings','POST',preset);note(d.message||'الگوی تنظیمات اعمال شد.');await loadCommunity()}
catch(e){note(e.message)}finally{button.disabled=false;button.textContent=old}
}
async function saveCommunitySetting(chatId,key,value,input){input.disabled=true;try{const d=await api('community/'+encodeURIComponent(chatId)+'/settings','POST',{settings:{[key]:value}});const item=communityItems.find(x=>String(x.chat_id)===String(chatId));if(item)item[key]=value;note(d.message)}catch(e){input.checked=!value;note(e.message)}finally{input.disabled=false}}
async function saveCommunityAdvanced(chatId,warnInput,floodInput,welcomeInput,wordsInput,button){
const warnLimit=Math.max(2,Math.min(5,Number.parseInt(warnInput.value,10)||3));
const floodLimit=Math.max(3,Math.min(20,Number.parseInt(floodInput.value,10)||7));
const welcomeMessage=welcomeInput.value.slice(0,500);
const words=wordsInput.value.split(/[\n,،;؛]+/).map(v=>v.trim()).filter(Boolean);
if(words.length>100||words.some(v=>v.length>60||/\s/.test(v))){note('حداکثر ۱۰۰ واژه کوتاه و بدون فاصله وارد کن.');return}
button.disabled=true;const original=button.textContent;button.textContent='در حال ذخیره…';
try{const d=await api('community/'+encodeURIComponent(chatId)+'/settings','POST',{settings:{},warn_limit:warnLimit,flood_limit:floodLimit,welcome_message:welcomeMessage,blocked_words:words});
const item=communityItems.find(x=>String(x.chat_id)===String(chatId));if(item){item.warn_limit=warnLimit;item.flood_limit=floodLimit;item.welcome_message=welcomeMessage;item.blocked_words=words}note(d.message||'تنظیمات پیشرفته ذخیره شد.');button.textContent='ذخیره شد ✓';
}catch(e){note(e.message);button.textContent='ذخیره ناموفق';}
finally{button.disabled=false;setTimeout(()=>{button.textContent=original},1300)}
}
function renderFeatureSettings(features,definitions){featureDraft={...features};const box=$('featureSettings');box.replaceChildren();Object.entries(definitions).forEach(([key,meta])=>{const row=document.createElement('label');row.className='listitem';row.style.cursor='pointer';const info=document.createElement('div');const title=document.createElement('b');title.textContent=meta.label;const desc=document.createElement('div');desc.className='muted';desc.textContent=meta.description;info.append(title,desc);const toggle=document.createElement('input');toggle.type='checkbox';toggle.checked=Boolean(featureDraft[key]);toggle.disabled=meta.available===false;toggle.setAttribute('aria-label',meta.label);toggle.style.width='20px';toggle.style.height='20px';toggle.addEventListener('change',()=>{featureDraft[key]=toggle.checked});row.append(info,toggle);box.append(row)});if(!box.children.length)box.innerHTML='<div class="empty">تنظیماتی برای نمایش وجود ندارد یا سطح دسترسی کافی نیست.</div>'}
async function saveFeatureSettings(){try{const d=await api('features','POST',{features:featureDraft});featureDraft={...d.features};$('featureSaveStatus').textContent=d.message;note(d.message);await refresh()}catch(e){$('featureSaveStatus').textContent=e.message;note(e.message)}}
function providerCards(){const html=Object.entries(labels).map(([id,label])=>{const ready=data.providers.includes(id);return '<div class="provider"><b><i class="dot '+(ready?'':'off')+'"></i>'+label+'</b><span>'+(ready?'آمادهٔ استفاده':'نیازمند تنظیم کلید API')+'</span></div>'}).join('');$('providerOverview').innerHTML=html;$('providerList').innerHTML=html;$('providerCount').textContent=data.providers.length}
async function refreshRequest(){if(refreshInProgress)return;refreshInProgress=true;try{data=await api('status');$('status').textContent='● متصل به سرور';$('users').textContent=data.users_count;$('adminsCount').textContent=data.admins_count??data.admins.length;$('bot').textContent=data.bot_enabled?'روشن':'خاموش';$('prompt').value=data.system_prompt;providerCards();if(data.permissions.includes('system'))renderFeatureSettings(data.features||{},data.feature_definitions||{});$('admins').innerHTML='';data.admins.forEach(username=>{const el=document.createElement('div');el.className='listitem';const label=document.createElement('span');label.textContent='مدیر پنل: '+username;const actions=document.createElement('div');actions.className='actions';const perms=document.createElement('button');perms.className='btn secondary';perms.textContent='دسترسی‌ها';perms.onclick=()=>managePermissions(username);actions.appendChild(perms);const b=document.createElement('button');b.className='btn danger';b.textContent='حذف';b.onclick=()=>removeAdmin(username);actions.appendChild(b);el.append(label,actions);const permissionLine=document.createElement('small');permissionLine.className='muted';permissionLine.textContent=(data.admin_permissions?.[String(username)]||['dashboard']).map(p=>permissionNames[p]||p).join(' · ');el.appendChild(permissionLine);$('admins').appendChild(el)});userItems=(data.recent_user_profiles||[]).slice().reverse();renderUsers();if(!userItems.length)$('userList').innerHTML='<div class="empty">هنوز کاربری ثبت نشده است.</div>';note('اطلاعات با موفقیت دریافت شد');if(document.getElementById('page-payments')?.classList.contains('active'))loadPayments()}catch(e){$('status').textContent='● خطا در اتصال';note(e.message)}finally{refreshInProgress=false}}
function renderUsers(){const q=($('userSearch')?.value||'').trim().toLocaleLowerCase('fa');const items=userItems.filter(p=>[p.display_name,p.first_name,p.last_name,p.username,p.user_id].some(v=>String(v??'').toLocaleLowerCase('fa').includes(q)));$('userList').innerHTML='';$('userCount').textContent=items.length+' کاربر';items.forEach(p=>{const el=document.createElement('div');el.className='listitem';el.style.display='flex';el.style.justifyContent='space-between';el.style.alignItems='center';el.style.gap='12px';const info=document.createElement('div');const title=document.createElement('b');title.textContent=p.display_name||[p.first_name,p.last_name].filter(Boolean).join(' ')||'نام ثبت نشده';const meta=document.createElement('small');meta.className='muted';meta.textContent='شناسه: '+p.user_id+' · '+(p.username?'@'+p.username:'بدون نام کاربری')+' · آخرین فعالیت: '+formatWhen(p.last_seen);const state=document.createElement('small');state.textContent=p.is_blocked?' · مسدود':' · فعال';state.style.color=p.is_blocked?'#ffaaaa':'#9de8bd';meta.append(state);info.append(title,meta);const action=document.createElement('button');action.type='button';action.className='btn '+(p.is_blocked?'secondary':'danger');action.textContent=p.is_blocked?'فعال‌سازی':'مسدودسازی';action.onclick=()=>setUserBlocked(p.user_id,!p.is_blocked);el.append(info,action);$('userList').appendChild(el)});if(!items.length)$('userList').innerHTML='<div class="empty">کاربری با این جست‌وجو پیدا نشد.</div>'}
async function setUserBlocked(userId,blocked){const verb=blocked?'مسدود':'فعال';if(!confirm('دسترسی این کاربر به ربات '+verb+' شود؟'))return;try{const d=await api('users/'+encodeURIComponent(userId)+'/'+(blocked?'block':'unblock'),'POST',{});note(d.message);await refresh()}catch(e){note(e.message)}}
function filterUsers(){renderUsers()}
async function toggleBot(){try{const d=await api('bot-state','POST',{enabled:!data.bot_enabled});note(d.message);await refresh()}catch(e){note(e.message)}}
const managerPermissionLabels={dashboard:'نمای کلی',providers:'سرویس‌های هوش مصنوعی',users:'کاربران',community:'گروه‌ها و کانال‌ها',conversations:'تاریخچه مکالمات',audit:'گزارش فعالیت‌ها',payments:'بررسی پرداخت‌ها',broadcast:'پیام همگانی',prompt:'دستورالعمل دستیار',system:'سلامت و تنظیمات'};
function initManagerPermissionChoices(){
const box=$('managerPermissionChoices');if(!box||box.dataset.ready==='1')return;
Object.entries(managerPermissionLabels).forEach(([key,label])=>{const wrap=document.createElement('label');const input=document.createElement('input');input.type='checkbox';input.value=key;input.checked=key==='dashboard';if(key==='dashboard')input.disabled=true;const span=document.createElement('span');span.textContent=label;wrap.append(input,span);box.append(wrap)});
box.dataset.ready='1';
}
async function addAdmin(){
initManagerPermissionChoices();
const button=document.querySelector('button[onclick="addAdmin()"]');
try{
const username=$('managerName').value.trim().toLowerCase();
const rawId=$('managerTelegramId').value.trim();
const telegram_id=Number(rawId);
const setup_code=$('managerSetupCode').value.trim();
if(!/^[a-zA-Z0-9_.-]{3,64}$/.test(username))throw Error('نام کاربری باید ۳ تا ۶۴ کاراکتر و فقط شامل حروف انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد.');
if(!/^[1-9][0-9]{0,14}$/.test(rawId)||!Number.isSafeInteger(telegram_id))throw Error('شناسه عددی تلگرام معتبر وارد کن.');
if(setup_code.length<8)throw Error('کد اختصاصی ساخت مدیر را وارد کن (حداقل ۸ کاراکتر).');
if(button){button.disabled=true;button.dataset.originalText=button.textContent;button.textContent='در حال ثبت مدیر…'}
note('در حال بررسی اطلاعات و ثبت حساب مدیر…');
const permissions=[...$('managerPermissionChoices').querySelectorAll('input:checked')].map(x=>x.value);if(!permissions.includes('dashboard'))permissions.push('dashboard');
const d=await api('managers','POST',{username,telegram_id,setup_code,permissions});
$('managerName').value='';$('managerTelegramId').value='';$('managerSetupCode').value='';
note(d.message||'✅ حساب مدیر ثبت شد؛ راهنمای ورود برای او ارسال شد.');
await refresh();
}catch(e){note('ثبت مدیر انجام نشد: '+e.message)}
finally{if(button){button.disabled=false;button.textContent=button.dataset.originalText||'ثبت مدیر'}}
}
async function resetAdminPassword(username){const password=prompt('رمز جدید مدیر «'+username+'» را وارد کن (دقیقاً ۴ کاراکتر):');if(password===null)return;if(password.length!==4)return note('رمز باید دقیقاً ۴ کاراکتر باشد');try{const d=await api('managers/'+encodeURIComponent(username)+'/password','POST',{password});note(d.message)}catch(e){note(e.message)}}
async function removeAdmin(username){if(!confirm('دسترسی مدیر «'+username+'» لغو شود؟'))return;try{const d=await api('managers/'+encodeURIComponent(username),'DELETE');note(d.message);await refresh()}catch(e){note(e.message)}}
function clearBroadcastImage(){const input=$('broadcastImage');if(input)input.value='';$('broadcastImagePreview').hidden=true;$('broadcastPreviewImg').removeAttribute('src')}
$('broadcastImage')?.addEventListener('change',()=>{const file=$('broadcastImage').files?.[0];if(!file){clearBroadcastImage();return}if(!['image/jpeg','image/png','image/webp'].includes(file.type)){clearBroadcastImage();note('فقط تصویر JPG، PNG یا WebP مجاز است');return}if(file.size>5*1024*1024){clearBroadcastImage();note('حجم تصویر باید حداکثر ۵ مگابایت باشد');return}const reader=new FileReader();reader.onload=()=>{$('broadcastPreviewImg').src=reader.result;$('broadcastImagePreview').hidden=false};reader.onerror=()=>note('خواندن تصویر ممکن نشد');reader.readAsDataURL(file)});
async function broadcast(){const text=$('broadcast').value.trim();const file=$('broadcastImage')?.files?.[0];if(!text&&!file)return note('متن یا تصویر پیام را وارد کن');const targets=[];if($('targetUsers')?.checked)targets.push('users');if($('targetGroups')?.checked)targets.push('groups');if($('targetChannels')?.checked)targets.push('channels');if(!targets.length)return note('حداقل یک نوع مخاطب را انتخاب کن');const names={users:'کاربران',groups:'گروه‌ها',channels:'کانال‌ها'};if(!confirm((file?'تصویر و متن ':'پیام ')+'برای این مخاطبان ارسال شود؟\n'+targets.map(x=>'• '+names[x]).join('\n')+'\n\nارسال قابل بازگشت نیست.'))return;try{const payload={text,targets};if(file){if(file.size>5*1024*1024)return note('حجم تصویر باید حداکثر ۵ مگابایت باشد');payload.image_mime=file.type;payload.image_name=file.name;payload.image_base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');reader.onerror=()=>reject(new Error('خواندن تصویر ممکن نشد'));reader.readAsDataURL(file)})}const d=await api('broadcast','POST',payload);const b=d.breakdown||{};const errors=(d.failure_samples||[]).map(x=>x.type+':'+x.chat_id+' — '+x.error);const imageStatus=file?(d.image_sent?'تصویر ارسال شد':'تصویر ارسال نشد'):'بدون تصویر';$('broadcastResult').textContent='کل: '+d.total+' · موفق: '+d.sent+' · ناموفق: '+d.failed+' | کاربران '+(b.users?.sent||0)+' | گروه‌ها '+(b.groups?.sent||0)+' | کانال‌ها '+(b.channels?.sent||0);note('ارسال همگانی تمام شد · '+imageStatus+(errors.length?' · خطاها: '+errors.join(' | '):''))}catch(e){note(e.message)}}
async function loadPaymentsRequest(){try{const d=await api('payments');$('pendingPayments').textContent=Number(d.pending||0).toLocaleString('fa-IR');$('allPayments').textContent=d.items.length.toLocaleString('fa-IR');$('confirmedPayments').textContent=Number(d.confirmed||0).toLocaleString('fa-IR');$('confirmedAmount').textContent=Number(d.total_amount_confirmed||0).toLocaleString('fa-IR');const box=$('paymentList');box.innerHTML='';if(!d.items.length){box.textContent='هنوز حمایتی ثبت نشده است.';return}d.items.forEach(p=>{const el=document.createElement('div');el.className='listitem';const info=document.createElement('div');const title=document.createElement('b');title.textContent=(p.full_name||'حامی ناشناس')+' · '+(p.username?'@'+p.username:'بدون نام کاربری')+' · '+p.user_id;const meta=document.createElement('div');meta.className='muted';meta.textContent='کد '+p.id+' · '+Number(p.amount_toman||0).toLocaleString('fa-IR')+' تومان · '+(p.status==='confirmed'?'تأییدشده':p.status==='pending_review'?'در انتظار بررسی':p.status||'نامشخص')+' · '+formatWhen(p.created_at)+' · OCR '+Math.round(Number(p.analysis?.confidence||0)*100)+'٪';info.append(title,meta);el.append(info);if(p.status==='pending_review'&&p.type==='donation'){const actions=document.createElement('div');actions.className='actions';const b=document.createElement('button');b.className='btn';b.textContent='❤️ تأیید دریافت حمایت';b.onclick=()=>reviewPayment(p.id,'confirm');actions.append(b);el.append(actions)}box.append(el)})}catch(e){note('دریافت حمایت‌ها ناموفق بود: '+e.message)}}
async function reviewPayment(id,action){const verb='تأیید دریافت حمایت و ارسال پیام تشکر';if(!confirm('حمایت '+id+' '+verb+' شود؟'))return;try{const d=await api('payments/'+id+'/'+action,'POST',{});note(d.message);await loadPayments();await refresh()}catch(e){note(e.message)}}
async function loadMetricsRequest(){try{const d=await api('metrics');$('communityChats').textContent=d.community_chats==null?'—':Number(d.community_chats).toLocaleString('fa-IR');$('communityMessages').textContent=d.community_messages==null?'—':Number(d.community_messages).toLocaleString('fa-IR');$('communityMembers').textContent=d.community_members_seen==null?'—':Number(d.community_members_seen).toLocaleString('fa-IR');$('communityPosts').textContent=d.community_top_posts==null?'—':Number(d.community_top_posts).toLocaleString('fa-IR');$('tgHealth').textContent=d.telegram_connected?'متصل':'قطع';$('dbHealth').textContent=d.database_ready?'آماده':'تنظیم‌نشده';$('modelHealth').textContent=d.providers_configured==null?'—':d.providers_configured+' / '+d.providers_total;$('serviceHealth').textContent=d.uptime_state==='running'?'فعال':'متوقف'}catch(e){note(e.message)}}
async function savePrompt(){try{const d=await api('prompt','POST',{prompt:$('prompt').value});note(d.message)}catch(e){note(e.message)}}
async function managePermissions(id){try{const d=await api('managers/'+encodeURIComponent(id)+'/permissions');editingAdminId=id;$('permissionsTitle').textContent='دسترسی‌های ادمین '+id;$('permissionsSubtitle').textContent='تغییرات بلافاصله در سمت سرور اعمال می‌شوند.';$('permissionsChoices').replaceChildren();Object.entries(d.available).forEach(([key,label])=>{const wrap=document.createElement('label');wrap.className='permission-option';const input=document.createElement('input');input.type='checkbox';input.value=key;input.checked=d.permissions.includes(key);input.disabled=!currentPermissions.has(key);const span=document.createElement('span');span.textContent=label+' · '+key;wrap.append(input,span);$('permissionsChoices').append(wrap)});$('permissionsStatus').textContent='';$('permissionsModal').hidden=false}catch(e){note(e.message)}}
function closePermissions(){$('permissionsModal').hidden=true;editingAdminId=null}
async function savePermissions(){if(!editingAdminId)return;const permissions=[...$('permissionsChoices').querySelectorAll('input:checked')].map(x=>x.value);if(!permissions.includes('dashboard'))permissions.push('dashboard');try{const d=await api('managers/'+encodeURIComponent(editingAdminId)+'/permissions','POST',{permissions});$('permissionsStatus').textContent=d.message;note(d.message);await refresh();setTimeout(closePermissions,900)}catch(e){$('permissionsStatus').textContent=e.message;note(e.message)}}

const activeViewLoads=new Map();
async function withViewLoading(pageIds,task){
 const pages=pageIds.map(id=>document.getElementById('page-'+id)).filter(Boolean);
 const indicators=[];
 for(const page of pages){
  const count=activeViewLoads.get(page.id)||0;activeViewLoads.set(page.id,count+1);
  page.setAttribute('aria-busy','true');
  let indicator=page.querySelector(':scope > .view-loading');
  if(!indicator){indicator=document.createElement('div');indicator.className='view-loading';indicator.setAttribute('role','status');indicator.setAttribute('aria-live','polite');indicator.textContent='در حال دریافت اطلاعات…';page.prepend(indicator)}
  indicators.push(page);
 }
 try{return await task()}
 finally{
  for(const page of indicators){const count=Math.max(0,(activeViewLoads.get(page.id)||1)-1);if(count===0){activeViewLoads.delete(page.id);page.removeAttribute('aria-busy');page.querySelector(':scope > .view-loading')?.remove()}else activeViewLoads.set(page.id,count)}
 }
}
async function loadConversations(){return withViewLoading(['conversations'],loadConversationsRequest)}
async function loadCommunity(){return withViewLoading(['community'],loadCommunityRequest)}
async function loadPayments(){return withViewLoading(['payments'],loadPaymentsRequest)}
async function loadMetrics(){return withViewLoading(['overview','system'],loadMetricsRequest)}
async function loadAudit(){return withViewLoading(['audit'],loadAuditRequest)}
async function refresh(){return withViewLoading(['overview'],refreshRequest)}

applyPermissions();
initManagerPermissionChoices();
document.querySelectorAll('.nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));$('page-'+b.dataset.page).classList.add('active');$('title').textContent=b.textContent.trim();if(b.dataset.page==='conversations')loadConversations();if(b.dataset.page==='payments')loadPayments();if(b.dataset.page==='system')loadMetrics();if(b.dataset.page==='overview')loadMetrics();if(b.dataset.page==='community')loadCommunity();if(b.dataset.page==='audit')loadAudit()});refresh();loadMetrics();
