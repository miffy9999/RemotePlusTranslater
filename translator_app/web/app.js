const $=s=>document.querySelector(s), feed=$('#feed'), empty=$('#empty'), phase=$('#phase strong');
const names={ja:'日本語',en:'English',ko:'한국어',es:'Español',zh:'中文',fr:'Français',de:'Deutsch',it:'Italiano',pt:'Português',ru:'Русский'};
const messages={
  ko:{subtitle:'오프라인 호텔 음성 통역',uiLanguage:'화면 언어',connecting:'연결 중',connected:'로컬 연결됨',reconnecting:'재연결 중',runtime:'실행 상태',starting:'시작 중',detectedLanguage:'현재 대화 언어',auto:'자동 감지',replyAuto:'최근 고객 언어',privacy:'처리 위치',localOnly:'이 PC · 오프라인',pause:'일시 정지',resume:'다시 시작',channelSettings:'번역 및 언어 설정',inputLanguage:'고객 입력 언어',replyLanguage:'답변 출력 언어',customerSpeech:'고객 음성',japaneseText:'일본어 텍스트',japaneseReply:'일본어 답변',customerTts:'고객 언어 음성',ttsOn:'TTS 켜짐',ttsOff:'TTS 꺼짐',output:'통합 번역 출력',outputHint:'원문과 일본어를 함께 표시합니다',loadingTitle:'모델을 준비하고 있습니다',loadingBody:'준비가 끝나면 고객 음성을 듣기 시작합니다.',incoming:'고객 · 일본어 번역',reply:'내 답변 · 음성 출력'},
  ja:{subtitle:'オフライン・ホテル音声通訳',uiLanguage:'表示言語',connecting:'接続中',connected:'ローカル接続済み',reconnecting:'再接続中',runtime:'実行状態',starting:'起動中',detectedLanguage:'現在の会話言語',auto:'自動検出',replyAuto:'直近のお客様の言語',privacy:'処理場所',localOnly:'このPC・オフライン',pause:'一時停止',resume:'再開',channelSettings:'翻訳・言語設定',inputLanguage:'お客様の入力言語',replyLanguage:'返答の出力言語',customerSpeech:'お客様の音声',japaneseText:'日本語テキスト',japaneseReply:'日本語の返答',customerTts:'お客様の言語音声',ttsOn:'TTS オン',ttsOff:'TTS オフ',output:'統合翻訳出力',outputHint:'原文と日本語を一緒に表示します',loadingTitle:'モデルを準備しています',loadingBody:'準備が完了すると音声認識を開始します。',incoming:'お客様・日本語訳',reply:'自分の返答・音声出力'},
  en:{subtitle:'Offline hotel voice interpreter',uiLanguage:'UI language',connecting:'Connecting',connected:'Local connection',reconnecting:'Reconnecting',runtime:'Runtime dashboard',starting:'Starting',detectedLanguage:'Conversation language',auto:'Auto detect',replyAuto:'Recent customer language',privacy:'Processing',localOnly:'This PC · Offline',pause:'Pause',resume:'Resume',channelSettings:'Translation and language settings',inputLanguage:'Customer input language',replyLanguage:'Reply output language',customerSpeech:'Customer speech',japaneseText:'Japanese text',japaneseReply:'Japanese reply',customerTts:'Customer-language audio',ttsOn:'TTS on',ttsOff:'TTS off',output:'Unified translation output',outputHint:'Shows the original and Japanese together',loadingTitle:'Preparing local models',loadingBody:'Listening starts when the models are ready.',incoming:'Customer · Japanese translation',reply:'My reply · Voice output'},
  zh:{subtitle:'离线酒店语音翻译',uiLanguage:'界面语言',connecting:'连接中',connected:'本地已连接',reconnecting:'正在重连',runtime:'运行状态',starting:'启动中',detectedLanguage:'当前会话语言',auto:'自动检测',replyAuto:'最近客人的语言',privacy:'处理位置',localOnly:'本机 · 离线',pause:'暂停',resume:'继续',channelSettings:'翻译与语言设置',inputLanguage:'客人输入语言',replyLanguage:'回复输出语言',customerSpeech:'客人语音',japaneseText:'日语文本',japaneseReply:'日语回复',customerTts:'客人语言语音',ttsOn:'TTS 开启',ttsOff:'TTS 关闭',output:'综合翻译输出',outputHint:'同时显示原文和日语',loadingTitle:'正在准备本地模型',loadingBody:'准备完成后开始接收语音。',incoming:'客人 · 日语翻译',reply:'我的回复 · 语音输出'},
  es:{subtitle:'Intérprete de voz hotelero sin conexión',uiLanguage:'Idioma de interfaz',connecting:'Conectando',connected:'Conexión local',reconnecting:'Reconectando',runtime:'Estado de ejecución',starting:'Iniciando',detectedLanguage:'Idioma de conversación',auto:'Detección automática',replyAuto:'Idioma reciente del cliente',privacy:'Procesamiento',localOnly:'Este PC · Sin conexión',pause:'Pausar',resume:'Continuar',channelSettings:'Traducción e idioma',inputLanguage:'Idioma del cliente',replyLanguage:'Idioma de salida de respuesta',customerSpeech:'Voz del cliente',japaneseText:'Texto japonés',japaneseReply:'Respuesta en japonés',customerTts:'Voz en idioma del cliente',ttsOn:'TTS activado',ttsOff:'TTS desactivado',output:'Salida de traducción',outputHint:'Muestra el original y el japonés',loadingTitle:'Preparando modelos locales',loadingBody:'La escucha comenzará cuando estén listos.',incoming:'Cliente · Traducción japonesa',reply:'Mi respuesta · Salida de voz'}
};
const deviceMessages={
  ko:{inputDevice:'음성 입력 장치',outputDevice:'TTS 출력 장치',systemDefault:'시스템 기본 장치',correct:'교정 기록',correctSource:'인식된 원문을 수정하세요',correctTranslation:'번역문을 수정하세요',saved:'교정을 로컬에 저장했습니다',languagePacks:'언어·음성팩',clearHistory:'기록 지우기',setupTitle:'사용할 고객 언어 선택',setupBody:'선택한 언어만 자동 감지와 수동 목록에 사용됩니다.',windowsSettings:'Windows 언어 설정',installVoices:'선택 음성팩 설치',save:'저장',installed:'설치됨',missing:'음성 없음',historyCleared:'화면 기록을 지웠습니다',selectLanguage:'언어를 하나 이상 선택하세요',restartAfterInstall:'설치 완료 후 프로그램을 다시 시작하세요'},
  ja:{inputDevice:'音声入力デバイス',outputDevice:'TTS出力デバイス',systemDefault:'システム既定',correct:'訂正を記録',correctSource:'認識された原文を修正してください',correctTranslation:'翻訳文を修正してください',saved:'訂正をローカルに保存しました',languagePacks:'言語・音声パック',clearHistory:'履歴を消去',setupTitle:'使用するお客様の言語',setupBody:'選択した言語だけを自動検出と手動選択に使用します。',windowsSettings:'Windows 言語設定',installVoices:'選択音声をインストール',save:'保存',installed:'インストール済み',missing:'音声なし',historyCleared:'表示履歴を消去しました',selectLanguage:'言語を1つ以上選択してください',restartAfterInstall:'インストール後にアプリを再起動してください'},
  en:{inputDevice:'Audio input device',outputDevice:'TTS output device',systemDefault:'System default',correct:'Record correction',correctSource:'Correct the recognized text',correctTranslation:'Correct the translation',saved:'Correction saved locally',languagePacks:'Languages & voices',clearHistory:'Clear history',setupTitle:'Choose customer languages',setupBody:'Only selected languages are used for automatic detection and manual selection.',windowsSettings:'Windows language settings',installVoices:'Install selected voices',save:'Save',installed:'Installed',missing:'Voice missing',historyCleared:'Display history cleared',selectLanguage:'Select at least one language',restartAfterInstall:'Restart the app after installation completes'},
  zh:{inputDevice:'音频输入设备',outputDevice:'TTS输出设备',systemDefault:'系统默认设备',correct:'记录更正',correctSource:'请更正识别的原文',correctTranslation:'请更正译文',saved:'更正已保存在本机',languagePacks:'语言和语音包',clearHistory:'清除记录',setupTitle:'选择客户语言',setupBody:'自动检测和手动选择仅使用所选语言。',windowsSettings:'Windows语言设置',installVoices:'安装所选语音',save:'保存',installed:'已安装',missing:'缺少语音',historyCleared:'显示记录已清除',selectLanguage:'请至少选择一种语言',restartAfterInstall:'安装完成后请重启程序'},
  es:{inputDevice:'Dispositivo de entrada',outputDevice:'Salida de TTS',systemDefault:'Dispositivo predeterminado',correct:'Guardar corrección',correctSource:'Corrige el texto reconocido',correctTranslation:'Corrige la traducción',saved:'Corrección guardada localmente',languagePacks:'Idiomas y voces',clearHistory:'Borrar historial',setupTitle:'Elegir idiomas del cliente',setupBody:'Solo se usarán los idiomas seleccionados en la detección y selección manual.',windowsSettings:'Configuración de Windows',installVoices:'Instalar voces elegidas',save:'Guardar',installed:'Instalado',missing:'Falta la voz',historyCleared:'Historial de pantalla borrado',selectLanguage:'Seleccione al menos un idioma',restartAfterInstall:'Reinicie la aplicación después de instalar'}
};
let ui=localStorage.getItem('remoteplus-ui-language')||'ja', state={tts_enabled:true,paused:false,speech_mode:'customer'}, retry=700, toastTimer,setupShown=false,missingDevices={input:0,output:0};
const modeMessages={
  ko:{speechMode:'인식 모드',staffSpeech:'직원 말하기 · Space 누르는 동안',staffSpeechActive:'직원 말하기 중 · 일본어 고정',setupBody:'선택한 언어를 고객 음성 인식과 번역에 사용합니다.'},
  ja:{speechMode:'認識モード',staffSpeech:'スタッフ発話・Spaceを押している間',staffSpeechActive:'スタッフ発話中・日本語固定',setupBody:'選択した言語をお客様の音声認識と翻訳に使用します。'},
  en:{speechMode:'Recognition mode',staffSpeech:'Staff speaking · hold Space',staffSpeechActive:'Staff speaking · Japanese fixed',setupBody:'Selected languages are used for customer speech recognition and translation.'},
  zh:{speechMode:'识别模式',staffSpeech:'员工说话 · 按住 Space',staffSpeechActive:'员工说话中 · 固定日语',setupBody:'所选语言用于客人语音识别和翻译。'},
  es:{speechMode:'Modo de reconocimiento',staffSpeech:'Personal hablando · mantener Space',staffSpeechActive:'Personal hablando · japonés fijo',setupBody:'Los idiomas seleccionados se usan para reconocer y traducir la voz del cliente.'}
};
const t=key=>modeMessages[ui]?.[key]||messages[ui]?.[key]||deviceMessages[ui]?.[key]||modeMessages.en[key]||messages.en[key]||deviceMessages.en[key]||key;
function applyI18n(){document.documentElement.lang=ui;document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=t(el.dataset.i18n));$('#ui-language').value=ui;applyState(state)}
function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),4200)}
function status(data){phase.textContent=data.message||data.phase||t('starting');$('.pulse').style.background=data.phase==='error'?'var(--red)':'var(--green)'}
function add(item){empty?.remove();const d=item.data||item;if(d.direction===undefined)return;const el=document.createElement('article');el.className='entry '+(d.direction==='reply'?'reply':'incoming');if(['重要語:','Important term:','중요 용어:','重要词语:','Término importante:'].some(mark=>d.translated.includes(mark)))el.classList.add('protected');const meta=document.createElement('div');meta.className='meta';const label=document.createElement('b');label.textContent=d.direction==='reply'?t('reply'):t('incoming');const tools=document.createElement('span');const timing=document.createElement('span');timing.textContent=d.latency_seconds?`${d.latency_seconds}s`:'';const correction=document.createElement('button');correction.className='correction';correction.textContent=t('correct');correction.onclick=()=>saveCorrection(d).catch(e=>toast(e.message));tools.append(timing,correction);meta.append(label,tools);const main=document.createElement('div');main.className='main';main.textContent=d.translated;const source=document.createElement('div');source.className='source';source.textContent=d.source;el.append(meta,main,source);feed.appendChild(el);while(feed.children.length>20)feed.removeChild(feed.firstChild);el.scrollIntoView({behavior:'smooth',block:'end'});if(d.direction==='incoming')setPartner(d.source_language)}
async function saveCorrection(d){const correctedSource=prompt(t('correctSource'),d.source);if(correctedSource===null)return;const correctedTranslation=prompt(t('correctTranslation'),d.translated);if(correctedTranslation===null)return;if(correctedSource===d.source&&correctedTranslation===d.translated)return;const r=await fetch('/api/feedback',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({direction:d.direction,source_language:d.source_language,source:d.source,translation:d.translated,corrected_source:correctedSource===d.source?'':correctedSource,corrected_translation:correctedTranslation===d.translated?'':correctedTranslation})});if(!r.ok)throw Error((await r.json()).detail||'Unable to save correction');toast(t('saved'))}
function setPartner(code){$('#partner').textContent=names[code]||code?.toUpperCase()||t('auto')}
function selectValue(id,value){const el=$(id),wanted=String(value);el.value=[...el.options].some(x=>x.value===wanted)?wanted:'default'}
function applyState(s){
  state={...state,...s};

  $('#tts').classList.toggle('on',!!state.tts_enabled);
  $('#tts').setAttribute('aria-pressed',!!state.tts_enabled);
  $('#tts em').textContent=state.tts_enabled?t('ttsOn'):t('ttsOff');

  $('#pause').textContent=state.paused?t('resume'):t('pause');

  const language=$('#language');
  if(state.input_language&&language?.options.length){
    selectValue('#language',state.input_language);
  }

  if(state.input_device!==undefined&&$('#input-device')?.options.length){
    selectValue('#input-device',state.input_device);
  }

  if(state.output_device!==undefined&&$('#output-device')?.options.length){
    selectValue('#output-device',state.output_device);
  }

  const staff=state.speech_mode==='staff';
  const mode=$('#speech-mode');
  if(mode){
    mode.classList.toggle('staff',staff);
    mode.setAttribute('aria-pressed',String(staff));
    mode.querySelector('em').textContent=staff?t('staffSpeechActive'):t('staffSpeech');
  }

  if(state.input_language){
    setPartner(state.input_language);
  }
}
async function loadDevices(){const r=await fetch('/api/devices');if(!r.ok)throw Error('Unable to load audio devices');const data=await r.json();for(const [id,items] of [['input-device',data.inputs],['output-device',data.outputs]]){const select=$('#'+id);while(select.options.length>1)select.remove(1);for(const item of items){const op=document.createElement('option');op.value=String(item.id);op.textContent=item.name;select.appendChild(op)}}const reset={};for(const [kind,id,key] of [['input','#input-device','input_device'],['output','#output-device','output_device']]){const selected=state[key];const present=selected==='default'||[...$(id).options].some(x=>x.value===String(selected));missingDevices[kind]=present?0:missingDevices[kind]+1;if(!present&&missingDevices[kind]>=2){reset[key]='default';missingDevices[kind]=0}}if(Object.keys(reset).length)await control(reset);else applyState(state)}
function renderLanguages(languages){
  const input=$('#language');
  const inputSelected=state.input_language||'';

  input.replaceChildren();

  for(const lang of languages){
    const op=document.createElement('option');
    op.value=lang.code;
    op.textContent=`${lang.native_name} · ${lang.name}`;
    input.appendChild(op);
  }

  selectValue('#language',inputSelected||input.options[0]?.value||'');
}
function clearFeed(){feed.replaceChildren(empty);toast(t('historyCleared'))}
async function openSetup(force=false){if(setupShown&&!force)return;const r=await fetch('/api/language-setup');if(!r.ok)throw Error('Unable to load language setup');const data=await r.json(),box=$('#setup-languages'),voiceMap=new Map(data.voices.map(v=>[v.code,v]));box.replaceChildren();for(const lang of data.available){const label=document.createElement('label'),input=document.createElement('input'),name=document.createElement('span'),status=document.createElement('small'),voice=voiceMap.get(lang.code);input.type='checkbox';input.value=lang.code;input.checked=data.enabled.includes(lang.code);name.textContent=`${lang.native_name} · ${lang.name}`;status.textContent=voice?.installed?t('installed'):t('missing');status.className=voice?.installed?'ok':'';label.append(input,name,status);box.append(label)}$('#setup-modal').hidden=false;setupShown=true}
function selectedSetupLanguages(){return [...document.querySelectorAll('#setup-languages input:checked')].map(x=>x.value)}
async function saveSetup(){const languages=selectedSetupLanguages();if(!languages.length){toast(t('selectLanguage'));return}const r=await fetch('/api/language-setup',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({languages})});if(!r.ok)throw Error((await r.json()).detail||'Unable to save languages');const data=await r.json();applyState(data.state);renderLanguages(data.languages);$('#setup-modal').hidden=true;setupShown=false}
async function installVoices(){const languages=selectedSetupLanguages();if(!languages.length){toast(t('selectLanguage'));return}if(!confirm(t('installVoices')+'?'))return;const r=await fetch('/api/install-voices',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({languages})});if(!r.ok)throw Error((await r.json()).detail||'Unable to start voice installer');toast(t('restartAfterInstall'))}
function snapshot(data){feed.replaceChildren(empty);applyState(data.state);status(data.state);renderLanguages(data.languages);for(const ev of data.history||[])if(ev.type==='translation')add(ev);if(data.setup_required)openSetup().catch(e=>toast(e.message))}
async function control(body){const r=await fetch('/api/control',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error((await r.json()).detail||'Unable to change setting');const snapshot=await r.json();applyState(snapshot);return snapshot}
$('#tts').onclick=()=>control({tts_enabled:!state.tts_enabled}).catch(e=>toast(e.message));
$('#pause').onclick=()=>control({paused:!state.paused}).catch(e=>toast(e.message));
$('#language').onchange=e=>control({active_language:e.target.value}).catch(e=>toast(e.message));
let spaceHeld=false, staffPointerHeld=false, modeRequestId=0;
function setSpeechMode(mode){
  if(state.speech_mode===mode)return;
  const requestId=++modeRequestId;
  applyState({speech_mode:mode});
  control({speech_mode:mode}).then(snapshot=>{
    if(requestId===modeRequestId)applyState(snapshot);
  }).catch(error=>{
    if(requestId===modeRequestId){
      toast(error.message);
      applyState({speech_mode:'customer'});
    }
  });
}
function enterStaffMode(){setSpeechMode('staff')}
function leaveStaffMode(){setSpeechMode('customer')}
function isTypingTarget(target){
  return Boolean(target?.closest?.('input,textarea,select,[contenteditable="true"]'));
}
const staffButton=$('#speech-mode');
staffButton.addEventListener('pointerdown',event=>{
  event.preventDefault();
  staffPointerHeld=true;
  staffButton.setPointerCapture?.(event.pointerId);
  enterStaffMode();
});
for(const eventName of ['pointerup','pointercancel','lostpointercapture']){
  staffButton.addEventListener(eventName,()=>{
    staffPointerHeld=false;
    if(!spaceHeld)leaveStaffMode();
  });
}
staffButton.addEventListener('click',event=>event.preventDefault());
window.addEventListener('keydown',event=>{
  if(event.code!=='Space'||event.repeat||spaceHeld||isTypingTarget(event.target))return;
  event.preventDefault();
  spaceHeld=true;
  enterStaffMode();
});
window.addEventListener('keyup',event=>{
  if(event.code!=='Space'||!spaceHeld)return;
  event.preventDefault();
  spaceHeld=false;
  if(!staffPointerHeld)leaveStaffMode();
});
function resetSpeechMode(){
  spaceHeld=false;
  staffPointerHeld=false;
  leaveStaffMode();
}
window.addEventListener('blur',resetSpeechMode);
document.addEventListener('visibilitychange',()=>{if(document.hidden)resetSpeechMode()});
$('#input-device').onchange=e=>{const value=e.target.value;const device=value==='default'||value.startsWith('loopback:')?value:Number(value);control({input_device:device}).catch(err=>toast(err.message))};
$('#output-device').onchange=e=>control({output_device:e.target.value}).catch(err=>toast(err.message));
$('#language-setup').onclick=()=>openSetup(true).catch(e=>toast(e.message));
$('#save-setup').onclick=()=>saveSetup().catch(e=>toast(e.message));
$('#install-voices').onclick=()=>installVoices().catch(e=>toast(e.message));
$('#open-voice-settings').onclick=()=>fetch('/api/voice-settings',{method:'POST'}).catch(e=>toast(e.message));
$('#clear-history').onclick=()=>{if(confirm(t('clearHistory')+'?'))fetch('/api/history',{method:'DELETE'}).then(r=>{if(!r.ok)throw Error('Unable to clear history');clearFeed()}).catch(e=>toast(e.message))};
$('#ui-language').onchange=e=>{ui=e.target.value;localStorage.setItem('remoteplus-ui-language',ui);applyI18n()};
function connect(){const protocol=location.protocol==='https:'?'wss':'ws',ws=new WebSocket(`${protocol}://${location.host}/ws`);ws.onopen=()=>{$('#connection').classList.add('on');$('#connection span').textContent=t('connected');retry=700};ws.onclose=()=>{$('#connection').classList.remove('on');$('#connection span').textContent=t('reconnecting');setTimeout(connect,retry);retry=Math.min(retry*1.7,8000)};ws.onmessage=e=>{const ev=JSON.parse(e.data);if(ev.type==='snapshot')snapshot(ev.data);else if(ev.type==='translation')add(ev);else if(ev.type==='status')status(ev.data);else if(ev.type==='state')applyState(ev.data);else if(ev.type==='history_cleared')clearFeed();else if(ev.type==='error'||ev.type==='warning')toast(ev.data.message)}}
applyI18n();loadDevices().catch(error=>toast(error.message));setInterval(()=>loadDevices().catch(()=>{}),10000);connect();
