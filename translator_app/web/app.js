const $ = selector => document.querySelector(selector);
const cards = new Map();
let ui = 'ja';
try { ui = localStorage.getItem('remoteplus-ui-language') || 'ja'; } catch {}
let state = {paused: false};
let languages = [];
let quickPhrases = [];
let quickPhraseLimit = 40;
let collapsedQuickPhraseCategories = new Set();
let collapsedQuickPhraseSave = Promise.resolve();
let quickPhraseCategorySaving = false;
let reconnectDelay = 700;
let toastTimer;

const messages = {
  ja: {subtitle:'フロントデスク翻訳チャット',uiLanguage:'表示言語',connecting:'接続中',connected:'ローカル接続済み',reconnecting:'再接続中',settings:'通話設定',starting:'起動中',customerLanguage:'お客様の言語',pause:'一時停止',resume:'再開',inputDevice:'音声入力デバイス',systemDefault:'システム既定',modeNote:'お客様の音声は日本語に翻訳されます。スタッフは右側に日本語を入力します。',conversation:'会話',latestFirst:'最新発話を優先',clear:'履歴を消去',loadingTitle:'システムを準備しています',loadingBody:'準備が完了するとお客様の音声を聞き始めます。',readyTitle:'システム準備完了',readyBody:'お客様の音声を待っています。',replyPlaceholder:'日本語で返答を入力…',translate:'翻訳',composerHint:'Enterで送信・Shift+Enterで改行。翻訳文の下にカタカナとローマ字の読み方が表示されます。',incoming:'お客様 → 日本語',reply:'スタッフ → お客様',katakana:'日本語読み',romanized:'ローマ字読み',translating:'翻訳中…',listening:'聞き取り中',recognizing:'音声認識中',paused:'一時停止中',warning:'注意',error:'エラー',emptyReply:'日本語の返答を入力してください。',sendFailed:'返答を送信できませんでした。'},
  ko: {subtitle:'프런트 데스크 번역 채팅',uiLanguage:'화면 언어',connecting:'연결 중',connected:'로컬 연결됨',reconnecting:'재연결 중',settings:'통화 설정',starting:'시작 중',customerLanguage:'고객 언어',pause:'일시 정지',resume:'다시 시작',inputDevice:'음성 입력 장치',systemDefault:'시스템 기본',modeNote:'고객 음성은 일본어로 번역됩니다. 직원은 오른쪽에 일본어 답변을 입력합니다.',conversation:'대화',latestFirst:'최신 발화 우선',clear:'기록 지우기',loadingTitle:'시스템을 준비하고 있습니다',loadingBody:'준비가 끝나면 고객 음성을 듣기 시작합니다.',readyTitle:'시스템 준비 완료',readyBody:'고객 음성을 기다리는 중입니다.',replyPlaceholder:'일본어로 답변 입력…',translate:'번역',composerHint:'Enter 전송·Shift+Enter 줄바꿈. 번역문 아래에 일본어 읽기와 로마자 읽기가 표시됩니다.',incoming:'고객 → 일본어',reply:'직원 → 고객',katakana:'일본어 읽기',romanized:'로마자 읽기',translating:'번역 중…',listening:'듣는 중',recognizing:'음성 인식 중',paused:'일시 정지됨',warning:'주의',error:'오류',emptyReply:'일본어 답변을 입력하세요.',sendFailed:'답변을 전송하지 못했습니다.'},
  en: {subtitle:'Front desk translation chat',uiLanguage:'UI language',connecting:'Connecting',connected:'Local connection',reconnecting:'Reconnecting',settings:'Call settings',starting:'Starting',customerLanguage:'Customer language',pause:'Pause',resume:'Resume',inputDevice:'Audio input device',systemDefault:'System default',modeNote:'Customer speech is translated into Japanese. Staff type Japanese replies on the right.',conversation:'Conversation',latestFirst:'Latest speech first',clear:'Clear history',loadingTitle:'Preparing the system',loadingBody:'Listening starts when the models are ready.',readyTitle:'System ready',readyBody:'Waiting for customer speech.',replyPlaceholder:'Type a reply in Japanese…',translate:'Translate',composerHint:'Enter to send, Shift+Enter for a new line. Katakana and romanized readings appear below replies.',incoming:'Customer → Japanese',reply:'Staff → Customer',katakana:'Japanese reading',romanized:'Romanized reading',translating:'Translating…',listening:'Listening',recognizing:'Recognizing speech',paused:'Paused',warning:'Warning',error:'Error',emptyReply:'Type a Japanese reply.',sendFailed:'Could not send the reply.'},
  zh: {subtitle:'前台翻译聊天',uiLanguage:'界面语言',connecting:'连接中',connected:'本地已连接',reconnecting:'正在重连',settings:'通话设置',starting:'启动中',customerLanguage:'客人语言',pause:'暂停',resume:'继续',inputDevice:'音频输入设备',systemDefault:'系统默认',modeNote:'客人的语音会被翻译成日语。员工在右侧输入日语回复。',conversation:'对话',latestFirst:'最新语音优先',clear:'清除记录',loadingTitle:'正在准备系统',loadingBody:'准备完成后开始接收客人语音。',readyTitle:'系统准备完成',readyBody:'正在等待客人语音。',replyPlaceholder:'用日语输入回复…',translate:'翻译',composerHint:'Enter发送，Shift+Enter换行。回复下方显示片假名和罗马字读法。',incoming:'客人 → 日语',reply:'员工 → 客人',katakana:'日语读法',romanized:'罗马字读法',translating:'翻译中…',listening:'正在聆听',recognizing:'语音识别中',paused:'已暂停',warning:'警告',error:'错误',emptyReply:'请输入日语回复。',sendFailed:'无法发送回复。'},
  es: {subtitle:'Chat de traducción de recepción',uiLanguage:'Idioma de interfaz',connecting:'Conectando',connected:'Conexión local',reconnecting:'Reconectando',settings:'Ajustes de llamada',starting:'Iniciando',customerLanguage:'Idioma del cliente',pause:'Pausar',resume:'Continuar',inputDevice:'Dispositivo de entrada',systemDefault:'Predeterminado',modeNote:'La voz del cliente se traduce al japonés. El personal escribe respuestas en japonés a la derecha.',conversation:'Conversación',latestFirst:'Última frase primero',clear:'Borrar historial',loadingTitle:'Preparando el sistema',loadingBody:'La escucha comienza cuando los modelos están listos.',readyTitle:'Sistema listo',readyBody:'Esperando la voz del cliente.',replyPlaceholder:'Escriba una respuesta en japonés…',translate:'Traducir',composerHint:'Enter para enviar, Shift+Enter para nueva línea. Las lecturas aparecen debajo.',incoming:'Cliente → Japonés',reply:'Personal → Cliente',katakana:'Lectura japonesa',romanized:'Lectura romanizada',translating:'Traduciendo…',listening:'Escuchando',recognizing:'Reconociendo voz',paused:'En pausa',warning:'Aviso',error:'Error',emptyReply:'Escriba una respuesta en japonés.',sendFailed:'No se pudo enviar la respuesta.'}
};

const phraseMessages = {
  ja: {quickPhrases:'よく使う文章',quickPhrasePlaceholder:'日本語・英語の文章を登録…',quickPhraseSearchPlaceholder:'日本語・英語の単語を検索…',noQuickPhrases:'登録された文章はありません。',noPhraseMatches:'一致する文章はありません。',uncategorized:'未分類',phraseCategory:'カテゴリー',saveCategory:'保存',clearCategory:'分類解除',deletePhrase:'削除',phraseLoaded:'入力欄に移動しました。',phraseAdded:'文章を登録しました。',categorySaved:'カテゴリーを保存しました。'},
  ko: {quickPhrases:'자주 쓰는 문장',quickPhrasePlaceholder:'일본어·영어 문장 등록…',quickPhraseSearchPlaceholder:'일본어·영어 단어 검색…',noQuickPhrases:'등록된 문장이 없습니다.',noPhraseMatches:'검색 결과가 없습니다.',uncategorized:'미분류',phraseCategory:'카테고리',saveCategory:'저장',clearCategory:'분류 해제',deletePhrase:'삭제',phraseLoaded:'번역 입력창으로 이동했습니다.',phraseAdded:'문장을 등록했습니다.',categorySaved:'카테고리를 저장했습니다.'},
  en: {quickPhrases:'Quick phrases',quickPhrasePlaceholder:'Register a Japanese or English phrase…',quickPhraseSearchPlaceholder:'Search for a Japanese or English word…',noQuickPhrases:'No phrases registered.',noPhraseMatches:'No matching phrases.',uncategorized:'Uncategorized',phraseCategory:'Category',saveCategory:'Save',clearCategory:'Remove category',deletePhrase:'Delete',phraseLoaded:'Moved to the translation box.',phraseAdded:'Phrase registered.',categorySaved:'Category saved.'},
  zh: {quickPhrases:'常用语句',quickPhrasePlaceholder:'添加日语句子…',quickPhraseSearchPlaceholder:'搜索句子中的词语…',noQuickPhrases:'尚未添加句子。',noPhraseMatches:'没有匹配的句子。',uncategorized:'未分类',phraseCategory:'分类',saveCategory:'保存',clearCategory:'取消分类',deletePhrase:'删除',phraseLoaded:'已移至翻译输入框。',phraseAdded:'句子已添加。',categorySaved:'分类已保存。'},
  es: {quickPhrases:'Frases frecuentes',quickPhrasePlaceholder:'Registrar una frase en japonés…',quickPhraseSearchPlaceholder:'Buscar una palabra en las frases…',noQuickPhrases:'No hay frases registradas.',noPhraseMatches:'No hay frases coincidentes.',uncategorized:'Sin categoría',phraseCategory:'Categoría',saveCategory:'Guardar',clearCategory:'Quitar categoría',deletePhrase:'Eliminar',phraseLoaded:'Se movió al cuadro de traducción.',phraseAdded:'Frase registrada.',categorySaved:'Categoría guardada.'}
};

function t(key) { return (phraseMessages[ui]||phraseMessages.ja)[key] || (messages[ui] || messages.ja)[key] || messages.ja[key] || key; }
function toast(message) { const el=$('#toast'); el.textContent=message; el.classList.add('show'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.classList.remove('show'),3500); }
function setTranslations() {
  document.documentElement.lang=ui;
  document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>{el.placeholder=t(el.dataset.i18nPlaceholder)});
  $('#ui-language').value=ui;
  renderState();
  cards.forEach(card=>updateCardLabels(card));
  renderQuickPhrases();
}
function languageName(code) { const item=languages.find(x=>x.code===code); return item ? `${item.native_name} · ${item.name}` : code || '-'; }
function updateCardLabels(card) {
  const direction=card.dataset.direction;
  card.querySelector('.meta b').textContent=direction==='reply'?t('reply'):t('incoming');
  const kana=card.querySelector('.kana-label'); if(kana) kana.textContent=t('katakana');
  const roman=card.querySelector('.roman-label'); if(roman) roman.textContent=t('romanized');
}
function makeCard(id, direction) {
  $('#empty').hidden=true;
  const article=document.createElement('article');
  article.className=`entry ${direction}`; article.dataset.direction=direction; article.dataset.id=id;
  article.innerHTML=`<div class="meta"><b></b><span class="lang"></span></div><div class="main"></div><div class="source"></div><div class="reading-guide" hidden><div><span class="reading-label kana-label"></span><strong class="reading-kana"></strong></div><div><span class="reading-label roman-label"></span><strong class="reading-roman"></strong></div></div>`;
  updateCardLabels(article); cards.set(String(id),article); $('#feed').appendChild(article); scrollFeed(); return article;
}
function scrollFeed(){const feed=$('#feed'); feed.scrollTop=feed.scrollHeight;}
function showTranscript(data) {
  if(data.speech_mode!=='staff') return;
  const id=String(data.utterance_id); const card=cards.get(id)||makeCard(id,'reply');
  card.querySelector('.source').textContent=data.text; card.querySelector('.main').textContent=t('translating');
}
function showTranslation(data) {
  const id=String(data.utterance_id); const direction=data.direction==='reply'?'reply':'incoming';
  const card=cards.get(id)||makeCard(id,direction); card.dataset.direction=direction; card.className=`entry ${direction}`;
  card.querySelector('.main').textContent=data.translated||''; card.querySelector('.source').textContent=data.source||'';
  card.querySelector('.lang').textContent=`${languageName(data.source_language)} → ${languageName(data.target_language)}`;
  updateCardLabels(card); if(data.reading||data.romanized_reading) showReading(data); scrollFeed();
}
function showReading(data) {
  const card=cards.get(String(data.utterance_id)); if(!card) return;
  const box=card.querySelector('.reading-guide');
  card.querySelector('.reading-kana').textContent=data.reading||'—';
  card.querySelector('.reading-roman').textContent=data.romanized_reading||'—';
  box.hidden=!(data.reading||data.romanized_reading); scrollFeed();
}
function phaseText(phase){return ({listening:t('listening'),recognizing:t('recognizing'),translating:t('translating'),paused:t('paused'),warning:t('warning'),error:t('error'),loading:t('starting'),starting:t('starting')})[phase]||phase;}
function renderState(){
  $('#pause').textContent=state.paused?t('resume'):t('pause');
  const phase=state.paused?'paused':state.phase||'starting'; $('#phase strong').textContent=phaseText(phase);
  $('#phase').className=`phase ${phase}`; if(state.input_language) $('#partner').textContent=languageName(state.input_language);
  const empty=$('#empty'); if(!cards.size){empty.hidden=false; const ready=state.ready&&state.translator_ready; empty.querySelector('h3').textContent=ready?t('readyTitle'):t('loadingTitle'); empty.querySelector('p').textContent=ready?t('readyBody'):t('loadingBody');}
}
function applyState(next){state={...state,...next}; renderState(); if(state.input_language&&$('#language').options.length) $('#language').value=state.input_language; if(state.input_device!==undefined&&$('#input-device').options.length) $('#input-device').value=String(state.input_device);}
async function api(path, options={}){const response=await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options}); if(!response.ok){let detail='';try{detail=(await response.json()).detail}catch{}throw Error(detail||`${response.status}`)}return response.status===204?{}:response.json();}
async function control(payload){applyState(await api('/api/control',{method:'POST',body:JSON.stringify(payload)}));}
function useQuickPhrase(text){const field=$('#reply-text');field.value=text;field.focus();field.setSelectionRange(text.length,text.length);field.scrollIntoView({block:'nearest'});toast(t('phraseLoaded'));}
function normalizePhraseSearch(value){return value.normalize('NFKC').toLocaleLowerCase('ja-JP');}
function storeLocalSetting(key,value){try{localStorage.setItem(key,value)}catch{}}
function persistCollapsedQuickPhraseCategories(){const collapsed_categories=[...collapsedQuickPhraseCategories];collapsedQuickPhraseSave=collapsedQuickPhraseSave.then(()=>api('/api/quick-phrases/ui-state',{method:'PATCH',body:JSON.stringify({collapsed_categories})})).catch(err=>toast(err.message));}
function toggleQuickPhraseCategory(category){if(collapsedQuickPhraseCategories.has(category))collapsedQuickPhraseCategories.delete(category);else collapsedQuickPhraseCategories.add(category);persistCollapsedQuickPhraseCategories();renderQuickPhrases();}
function closeQuickPhraseMenu(){const menu=$('#quick-phrase-menu');menu.hidden=true;delete menu.dataset.phraseId;}
function openQuickPhraseMenu(item,event){event.preventDefault();const menu=$('#quick-phrase-menu');menu.dataset.phraseId=item.id;const input=$('#quick-phrase-category');input.value=item.category||'';const categories=[...new Set(quickPhrases.map(x=>x.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,ui));const options=$('#quick-phrase-categories');options.replaceChildren();categories.forEach(category=>{const option=document.createElement('option');option.value=category;options.appendChild(option)});menu.hidden=false;const left=Math.min(event.clientX,window.innerWidth-menu.offsetWidth-8);const top=Math.min(event.clientY,window.innerHeight-menu.offsetHeight-8);menu.style.left=`${Math.max(8,left)}px`;menu.style.top=`${Math.max(8,top)}px`;input.focus();input.select();}
async function updateQuickPhraseCategory(category){const menu=$('#quick-phrase-menu');const phraseId=menu.dataset.phraseId;if(!phraseId||quickPhraseCategorySaving)return;quickPhraseCategorySaving=true;$('#save-quick-phrase-category').disabled=true;$('#clear-quick-phrase-category').disabled=true;try{const data=await api(`/api/quick-phrases/${encodeURIComponent(phraseId)}/category`,{method:'PATCH',body:JSON.stringify({category})});const index=quickPhrases.findIndex(item=>item.id===phraseId);if(index>=0)quickPhrases[index]=data.phrase;collapsedQuickPhraseCategories.delete(data.phrase.category||'');persistCollapsedQuickPhraseCategories();closeQuickPhraseMenu();renderQuickPhrases();toast(t('categorySaved'))}catch(err){toast(err.message)}finally{quickPhraseCategorySaving=false;$('#save-quick-phrase-category').disabled=false;$('#clear-quick-phrase-category').disabled=false;}}
function createQuickPhraseRow(item){
  const row=document.createElement('div');
  row.className='quick-phrase-row';
  row.oncontextmenu=event=>openQuickPhraseMenu(item,event);
  const use=document.createElement('button');
  use.type='button';
  use.className='quick-phrase-use';
  use.textContent=item.text;
  use.onclick=()=>useQuickPhrase(item.text);
  const remove=document.createElement('button');
  remove.type='button';
  remove.className='quick-phrase-delete';
  remove.textContent='×';
  remove.title=t('deletePhrase');
  remove.setAttribute('aria-label',t('deletePhrase'));
  remove.onclick=async()=>{try{await api(`/api/quick-phrases/${encodeURIComponent(item.id)}`,{method:'DELETE'});quickPhrases=quickPhrases.filter(x=>x.id!==item.id);closeQuickPhraseMenu();renderQuickPhrases()}catch(err){toast(err.message)}};
  row.append(use,remove);
  return row;
}
function renderQuickPhrases(){
  const list=$('#quick-phrase-list');
  if(!list)return;
  list.replaceChildren();
  $('#quick-phrase-count').textContent=`${quickPhrases.length} / ${quickPhraseLimit}`;
  const query=normalizePhraseSearch(($('#quick-phrase-search').value||'').trim());
  const filtered=quickPhrases.filter(item=>!query||normalizePhraseSearch(item.text).includes(query)||normalizePhraseSearch(item.category||'').includes(query));
  const empty=$('#quick-phrase-empty');
  empty.hidden=filtered.length>0;
  empty.textContent=quickPhrases.length&&query?t('noPhraseMatches'):t('noQuickPhrases');
  const groups=new Map();
  filtered.forEach(item=>{const category=item.category||'';if(!groups.has(category))groups.set(category,[]);groups.get(category).push(item)});
  const categories=[...groups.keys()].sort((a,b)=>!a?1:!b?-1:a.localeCompare(b,ui));
  categories.forEach(category=>{
    const items=groups.get(category);
    const collapsed=!query&&collapsedQuickPhraseCategories.has(category);
    const group=document.createElement('section');
    group.className=`quick-phrase-group${collapsed?' collapsed':''}`;
    const toggle=document.createElement('button');
    toggle.type='button';
    toggle.className='quick-phrase-group-toggle';
    toggle.setAttribute('aria-expanded',String(!collapsed));
    toggle.disabled=Boolean(query);
    const label=document.createElement('span');
    label.textContent=category||t('uncategorized');
    const count=document.createElement('small');
    count.textContent=String(items.length);
    toggle.append(label,count);
    if(!query)toggle.onclick=()=>toggleQuickPhraseCategory(category);
    group.appendChild(toggle);
    const body=document.createElement('div');
    body.className='quick-phrase-group-body';
    items.forEach(item=>body.appendChild(createQuickPhraseRow(item)));
    group.appendChild(body);
    list.appendChild(group);
  });
}
async function loadInitial(){
  const data=await api('/api/state');
  languages=data.languages||[];
  const select=$('#language');
  select.replaceChildren();
  languages.forEach(item=>{const option=document.createElement('option');option.value=item.code;option.textContent=`${item.native_name} · ${item.name}`;select.appendChild(option)});
  (data.history||[]).forEach(event=>handleEvent(event));
  applyState(data.state||{});
  try{
    const phraseData=await api('/api/quick-phrases');
    quickPhrases=phraseData.phrases||[];
    quickPhraseLimit=phraseData.max_items||40;
    collapsedQuickPhraseCategories=new Set(phraseData.collapsed_categories||[]);
    renderQuickPhrases();
  }catch(err){toast(err.message)}
  try{
    const devices=await api('/api/devices');
    const input=$('#input-device');
    input.replaceChildren();
    const def=document.createElement('option');
    def.value='default';
    def.textContent=t('systemDefault');
    input.appendChild(def);
    (devices.inputs||[]).filter(x=>x.id!=='default').forEach(item=>{const option=document.createElement('option');option.value=item.id;option.textContent=item.name;input.appendChild(option)});
    input.value=String(state.input_device||'default');
    if(devices.warnings?.length)toast(devices.warnings[0]);
  }catch(err){toast(err.message)}
}
function handleEvent(event){const data=event.data||event; if(event.type==='translation')showTranslation(data); else if(event.type==='reading')showReading(data); else if(event.type==='transcript')showTranscript(data); else if(event.type==='status')applyState(data); else if(event.type==='state')applyState(data); else if(event.type==='history_cleared'){cards.forEach(x=>x.remove());cards.clear();renderState();} else if(event.type==='warning'||event.type==='error')toast(data.message||event.type);}
function connect(){const scheme=location.protocol==='https:'?'wss':'ws';const ws=new WebSocket(`${scheme}://${location.host}/ws`); $('#connection span').textContent=t('connecting');ws.onopen=()=>{reconnectDelay=700;$('#connection').classList.add('online');$('#connection span').textContent=t('connected')};ws.onmessage=e=>{try{const event=JSON.parse(e.data);if(event.type==='snapshot'){const payload=event.data||{};(payload.history||[]).forEach(handleEvent);applyState(payload.state||{})}else handleEvent(event)}catch{}};ws.onclose=()=>{$('#connection').classList.remove('online');$('#connection span').textContent=t('reconnecting');setTimeout(connect,reconnectDelay);reconnectDelay=Math.min(8000,reconnectDelay*1.6)};}

$('#ui-language').onchange=e=>{ui=e.target.value;storeLocalSetting('remoteplus-ui-language',ui);setTranslations()};
$('#language').onchange=e=>control({active_language:e.target.value,reply_language:'auto'}).catch(err=>toast(err.message));
$('#input-device').onchange=e=>control({input_device:e.target.value}).catch(err=>toast(err.message));
$('#pause').onclick=()=>control({paused:!state.paused}).catch(err=>toast(err.message));
$('#clear-history').onclick=async()=>{try{await api('/api/history',{method:'DELETE'});cards.forEach(x=>x.remove());cards.clear();renderState()}catch(err){toast(err.message)}};
$('#reply-form').onsubmit=async event=>{event.preventDefault();const field=$('#reply-text');const text=field.value.trim();if(!text){toast(t('emptyReply'));return}const button=$('#send-reply');button.disabled=true;try{await api('/api/reply',{method:'POST',body:JSON.stringify({text})});field.value=''}catch(err){toast(`${t('sendFailed')} ${err.message}`)}finally{button.disabled=false;field.focus()}};
$('#reply-text').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('#reply-form').requestSubmit()}};
$('#quick-phrase-form').onsubmit=async event=>{event.preventDefault();const field=$('#quick-phrase-text');const text=field.value.trim();if(!text)return;const button=$('#add-quick-phrase');button.disabled=true;try{const data=await api('/api/quick-phrases',{method:'POST',body:JSON.stringify({text})});quickPhrases.push(data.phrase);field.value='';$('#quick-phrase-search').value='';collapsedQuickPhraseCategories.delete('');persistCollapsedQuickPhraseCategories();renderQuickPhrases();toast(t('phraseAdded'))}catch(err){toast(err.message)}finally{button.disabled=false;field.focus()}};
$('#quick-phrase-search').oninput=renderQuickPhrases;
$('#save-quick-phrase-category').onclick=()=>updateQuickPhraseCategory($('#quick-phrase-category').value);
$('#clear-quick-phrase-category').onclick=()=>updateQuickPhraseCategory('');
$('#quick-phrase-category').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();updateQuickPhraseCategory(event.target.value)}else if(event.key==='Escape')closeQuickPhraseMenu()};
document.addEventListener('click',event=>{const menu=$('#quick-phrase-menu');if(!menu.hidden&&!menu.contains(event.target))closeQuickPhraseMenu()});
window.addEventListener('blur',closeQuickPhraseMenu);

setTranslations();
loadInitial().then(connect).catch(err=>{toast(err.message);connect()});
