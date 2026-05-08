const API_BASE = window.location.origin;

const translations = {
  en: {
    eyebrow: 'AI Search Project', title: 'AI-Based PC Builder', subtitle: 'Generate a compatible PC build using BFS, DFS, UCS, or A* based on your budget and purpose.',
    controls: 'Build Controls', budget: 'Budget', purpose: 'Purpose', algorithm: 'Search Algorithm', currency: 'Currency', generate: 'Generate Build',
    hint: 'The backend loads the Excel file automatically from backend/data.', recommended: 'Recommended Build', totalPrice: 'Total Price', usedAlgorithm: 'Algorithm',
    states: 'Explored States', score: 'Score', empty: 'Click Generate Build to start.', compatible: 'Compatible', notCompatible: 'Not Compatible', loading: 'Generating build...', apiOk: 'API Online', apiBad: 'API Offline'
  },
  ar: {
    eyebrow: 'مشروع بحث بالذكاء الاصطناعي', title: 'منشئ كمبيوتر بالذكاء الاصطناعي', subtitle: 'ولّد تجميعة كمبيوتر متوافقة حسب الميزانية والاستخدام والخوارزمية المختارة.',
    controls: 'إعدادات التجميعة', budget: 'الميزانية', purpose: 'الاستخدام', algorithm: 'خوارزمية البحث', currency: 'العملة', generate: 'إنشاء التجميعة',
    hint: 'الباكند يقرأ ملف Excel تلقائيًا من backend/data.', recommended: 'التجميعة المقترحة', totalPrice: 'السعر الإجمالي', usedAlgorithm: 'الخوارزمية',
    states: 'الحالات المستكشفة', score: 'التقييم', empty: 'اضغط إنشاء التجميعة للبدء.', compatible: 'متوافقة', notCompatible: 'غير متوافقة', loading: 'جاري إنشاء التجميعة...', apiOk: 'API يعمل', apiBad: 'API لا يعمل'
  }
};

let lang = 'en';
const icons = { CPU: '🧠', Motherboard: '🔌', RAM: '💾', Storage: '🗄️', GPU: '🎮', PSU: '⚡' };

function t(key) { return translations[lang][key] || key; }

function applyLanguage() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.body.setAttribute('dir', document.documentElement.dir);
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.getElementById('langBtn').textContent = lang === 'en' ? 'العربية' : 'English';
}

function formatMoney(value, symbol, currency) {
  if (currency === 'SAR' || currency === 'AED' || currency === 'KWD') return `${value} ${symbol}`;
  return `${symbol}${value}`;
}

function specsFor(category, item) {
  if (!item) return [];
  if (category === 'CPU') return [`${item.cores} Cores`, `${item.threads} Threads`, item.socket, `${item.tdp_watts}W`];
  if (category === 'Motherboard') return [item.socket, item.ram_type, `${item.m2_slots} M.2`, `${item.sata_ports} SATA`];
  if (category === 'RAM') return [item.type, `${item.capacity_gb}GB`, `${item.speed_mhz}MHz`];
  if (category === 'Storage') return [item.interface, `${item.capacity_gb}GB`, `${item.read_mbps} MB/s`];
  if (category === 'GPU') return [`${item.vram_gb}GB VRAM`, `${item.tdp_watts}W`, item.brand];
  if (category === 'PSU') return [`${item.wattage}W`, item.efficiency, item.modular ? `Modular: ${item.modular}` : ''];
  return [];
}

function renderBuild(data) {
  const components = document.getElementById('components');
  const message = document.getElementById('message');
  const badge = document.getElementById('compatBadge');
  components.innerHTML = '';

  document.getElementById('totalPrice').textContent = data.success ? formatMoney(data.total_price, data.currency_symbol, data.currency) : '-';
  document.getElementById('usedAlgorithm').textContent = data.algorithm || '-';
  document.getElementById('states').textContent = data.explored_states ?? '-';
  document.getElementById('score').textContent = data.score ?? '-';

  badge.className = `compat ${data.compatibility_status ? 'ok' : 'bad'}`;
  badge.textContent = data.compatibility_status ? t('compatible') : t('notCompatible');
  message.textContent = data.message || data.error || '-';

  if (!data.success) return;

  Object.entries(data.build).forEach(([category, item]) => {
    if (!item) return;
    const card = document.createElement('article');
    card.className = 'part-card';
    const specTags = specsFor(category, item).filter(Boolean).map(s => `<span>${s}</span>`).join('');
    card.innerHTML = `
      <div class="part-top">
        <div>
          <h3>${category}</h3>
          <p>${item.name}</p>
        </div>
        <div class="icon">${icons[category] || '🧩'}</div>
      </div>
      <div class="specs">${specTags}</div>
      <p class="price">$${Number(item.price_usd || 0).toFixed(2)} USD</p>
    `;
    components.appendChild(card);
  });
}

async function checkApi() {
  const pill = document.getElementById('apiStatus');
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) throw new Error('offline');
    pill.textContent = t('apiOk');
    pill.className = 'status-pill ok';
  } catch (error) {
    pill.textContent = t('apiBad');
    pill.className = 'status-pill bad';
  }
}

async function generateBuild() {
  const payload = {
    budget: Number(document.getElementById('budget').value),
    purpose: document.getElementById('purpose').value,
    algorithm: document.getElementById('algorithm').value,
    currency: document.getElementById('currency').value
  };

  document.getElementById('message').textContent = t('loading');
  document.getElementById('components').innerHTML = '';

  try {
    const res = await fetch(`${API_BASE}/api/build`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    renderBuild(data);
  } catch (error) {
    renderBuild({ success: false, compatibility_status: false, error: error.message, explored_states: '-', algorithm: payload.algorithm });
  }
}

document.getElementById('generateBtn').addEventListener('click', generateBuild);
document.getElementById('langBtn').addEventListener('click', () => { lang = lang === 'en' ? 'ar' : 'en'; applyLanguage(); checkApi(); });

applyLanguage();
checkApi();
