/* Расписание УМПК — клиентская часть (без сборки и зависимостей) */
'use strict';

const App = {
  data: null,            // всё расписание, прочитанное из data/schedule.json
  meta: null,            // справочник для экранов: группы, преподаватели, недели
  root: document.getElementById('app'),
  weekIndex: null,       // какая из опубликованных недель открыта
  tick: null,          // перерисовка раз в минуту, чтобы «сейчас» и «прошло» не устаревали
};

const RECENT_KEY = 'umpk.recent.v1';
const THEME_KEY = 'umpk.theme';
const MAX_RECENT = 3;

/* ----------------------------------------------------------- утилиты ---- */

const tpl = (id) => document.getElementById(id).content.cloneNode(true);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function isoDate(date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return shifted.toISOString().slice(0, 10);
}

function addDays(date, days) {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function dayLabel(date) {
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
}

function mondayOf(date) {
  return addDays(date, -((date.getDay() + 6) % 7));
}

/* ------------------------------------------------------------- данные --- */

const DATA_URL = 'data/schedule.json';
const WEEKDAY_NAMES = {
  1: 'Понедельник', 2: 'Вторник', 3: 'Среда',
  4: 'Четверг', 5: 'Пятница', 6: 'Суббота', 7: 'Воскресенье',
};

/**
 * Читает расписание одним файлом и раскладывает по группам и преподавателям.
 * Сервер не нужен: весь семестр — около 50 КБ в сжатом виде.
 */
async function loadData() {
  const data = await api(DATA_URL);
  data.byGroup = new Map();
  data.byTeacher = new Map();
  data.removedByGroup = new Map();
  data.removedByTeacher = new Map();

  const put = (map, key, lesson) => {
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(lesson);
  };

  for (const lesson of data.lessons) {
    put(data.byGroup, lesson.group, lesson);
    if (lesson.teacher) put(data.byTeacher, lesson.teacher, lesson);
  }
  // Пары, снятые с расписания: их больше нет, но несколько дней показываем
  // зачёркнутыми — иначе человек не заметит, что занятие отменили.
  for (const lesson of data.removed || []) {
    put(data.removedByGroup, lesson.group, lesson);
    if (lesson.teacher) put(data.removedByTeacher, lesson.teacher, lesson);
  }
  return data;
}

/** 1 — нечётная неделя, 2 — чётная. Отсчёт от первого понедельника из таблиц. */
function weekNumber(date) {
  const anchor = mondayOf(new Date(App.data.anchor_monday + 'T00:00:00'));
  const delta = Math.round((mondayOf(date) - anchor) / 604800000);
  return Math.abs(delta) % 2 === 0 ? 1 : 2;
}

const shortDate = (date) =>
  `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}`;

/**
 * Недели, которые колледж выложил — у них в таблицах проставлены даты.
 * Текущая неделя добавляется всегда, иначе при отставших таблицах сайт
 * показывал бы пары на сегодня, но не давал открыть эту неделю целиком.
 */
function publishedWeeks() {
  const weeks = new Map();
  for (const item of (App.data && App.data.weeks) || []) weeks.set(item.monday, item.week);

  const today = new Date();
  const monday = isoDate(mondayOf(today));
  if (!weeks.has(monday)) weeks.set(monday, App.data ? weekNumber(today) : 1);

  return [...weeks.entries()].sort((a, b) => a[0].localeCompare(b[0]))
    .map(([iso, week]) => {
      const start = new Date(iso + 'T00:00:00');
      const end = addDays(start, 5);
      return {
        monday: iso,
        week,
        label: `${dayLabel(start)} — ${dayLabel(end)}`,
        short: `${shortDate(start)} — ${shortDate(end)}`,
      };
    });
}

function scheduleFor(kind, name, start, days) {
  const forGroup = kind === 'group';
  const source = (forGroup ? App.data.byGroup : App.data.byTeacher).get(name) || [];
  const gone = (forGroup ? App.data.removedByGroup : App.data.removedByTeacher).get(name) || [];

  const onDay = (list, weekday, week) => list
    .filter((l) => l.weekday === weekday && (l.week === 0 || l.week === week))
    .sort((a, b) => a.pair - b.pair || (a.subgroup || 0) - (b.subgroup || 0));

  const result = [];
  for (let offset = 0; offset < days; offset++) {
    const day = addDays(start, offset);
    const weekday = ((day.getDay() + 6) % 7) + 1;      // 1 = понедельник
    const week = weekNumber(day);
    result.push({
      date: isoDate(day),
      weekday,
      weekday_name: WEEKDAY_NAMES[weekday],
      date_label: dayLabel(day),
      week,
      lessons: weekday === 7 ? [] : onDay(source, weekday, week),
      removed: weekday === 7 ? [] : onDay(gone, weekday, week),
    });
  }
  return { kind, name, found: source.length > 0, days: result };
}

function currentWeekIndex(list) {
  const monday = isoDate(mondayOf(new Date()));
  const index = list.findIndex((item) => item.monday === monday);
  return index >= 0 ? index : list.length - 1;
}

/** Нормализация для поиска: регистр, ё, лишние пробелы. */
function normalize(text) {
  return text.toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim();
}

/**
 * «1 БД» -> { course: 1, speciality: 'БД' }
 * «2 ОИБАС А» -> { course: 2, speciality: 'ОИБАС' } — литера потока не влияет
 * на специальность, иначе список распался бы на «ОИБАС А», «ОИБАС Б» и т.д.
 */
function splitGroup(name) {
  const match = name.match(/^\s*(\d+)\s+(.*)$/);
  const course = match ? Number(match[1]) : 0;
  let rest = (match ? match[2] : name).trim();
  rest = rest.replace(/\s*\(\d+\)\s*$/, '');      // «3 ТИК А (2)» — дубль в исходнике
  rest = rest.replace(/\s+[А-ЯЁ]$/, '');          // литера потока: А, Б, В
  return { course, speciality: rest || name.trim() };
}

function readRecent() {
  try {
    const stored = JSON.parse(localStorage.getItem(RECENT_KEY));
    return Array.isArray(stored) ? stored : [];
  } catch { return []; }
}

function pushRecent(kind, name) {
  const list = readRecent().filter((item) => !(item.kind === kind && item.name === name));
  list.unshift({ kind, name });
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, MAX_RECENT))); } catch { /* приватный режим */ }
}

const routeFor = (kind, name) =>
  `#/${kind === 'group' ? 'g' : 't'}/${encodeURIComponent(name)}`;

/* ------------------------------------------------------------- шапка ---- */

const burger = document.getElementById('burger');
const nav = document.getElementById('nav');

burger.addEventListener('click', () => {
  const open = nav.classList.toggle('is-open');
  burger.setAttribute('aria-expanded', String(open));
});
document.getElementById('year').textContent = String(new Date().getFullYear());

/* --------------------------------------------------------------- тема --- */

function storedTheme() {
  try { return localStorage.getItem(THEME_KEY) || 'system'; } catch { return 'system'; }
}

function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === 'light' || choice === 'dark') root.setAttribute('data-theme', choice);
  else root.removeAttribute('data-theme');

  try {
    if (choice === 'system') localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, choice);
  } catch { /* приватный режим */ }

  document.querySelectorAll('.theme__btn').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.themeChoice === choice);
  });

  // Цвет строки состояния в мобильных браузерах — под фон шапки.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    const surface = getComputedStyle(root).getPropertyValue('--surface').trim();
    if (surface) meta.content = surface;
  }
}

// Кнопки темы и установки живут в двух местах и перерисовываются,
// поэтому слушаем клики на документе, а не на конкретных элементах.
document.addEventListener('click', (event) => {
  const themeButton = event.target.closest('.theme__btn');
  if (themeButton) {
    applyTheme(themeButton.dataset.themeChoice);
    return;
  }
  if (event.target.closest('.install')) {
    nav.classList.remove('is-open');
    burger.setAttribute('aria-expanded', 'false');
    openInstallModal();
  }
});

// Пока выбрано «Авто», следим за настройкой системы.
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (storedTheme() === 'system') applyTheme('system');
});

applyTheme(storedTheme());

/* ---------------------------------------------------------- установка --- */

const INSTALL_GUIDES = {
  ios: {
    title: 'iPhone и iPad — Safari',
    items: [
      'Нажмите <b>Поделиться</b> — квадрат со стрелкой вверх внизу экрана.',
      'Пролистайте список вниз.',
      'Выберите <b>«На экран „Домой“»</b>.',
      'Нажмите <b>«Добавить»</b> в правом верхнем углу.',
    ],
  },
  android: {
    title: 'Android — Chrome',
    items: [
      'Нажмите <b>⋮</b> в правом верхнем углу браузера.',
      'Выберите <b>«Установить приложение»</b> или <b>«Добавить на главный экран»</b>.',
      'Подтвердите установку.',
    ],
  },
  desktop: {
    title: 'Компьютер — Chrome, Edge, Яндекс Браузер',
    items: [
      'Нажмите значок установки в правой части адресной строки.',
      'Или откройте меню браузера и выберите <b>«Установить „Расписание УМПК“»</b>.',
      'Ярлык появится на рабочем столе и в меню «Пуск».',
    ],
  },
};

let installPrompt = null;

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  installPrompt = event;
});

function detectPlatform() {
  const ua = navigator.userAgent;
  const iPadOS = navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  if (/iPhone|iPad|iPod/i.test(ua) || iPadOS) return 'ios';
  if (/Android/i.test(ua)) return 'android';
  return 'desktop';
}

const installModal = document.getElementById('install-modal');

function openInstallModal() {
  const platform = detectPlatform();
  const order = [platform, ...Object.keys(INSTALL_GUIDES).filter((key) => key !== platform)];

  const steps = document.getElementById('install-steps');
  steps.replaceChildren(...order.map((key) => {
    const guide = INSTALL_GUIDES[key];
    const block = el('div', 'step');
    block.append(el('h3', 'step__title', guide.title));
    const list = el('ol', 'step__list');
    for (const item of guide.items) {
      const li = document.createElement('li');
      li.innerHTML = item;          // строки заданы здесь же, данных снаружи нет
      list.append(li);
    }
    block.append(list);
    return block;
  }));

  const action = document.getElementById('install-now');
  action.hidden = !installPrompt;

  // Chrome и Edge разрешают установку только на localhost или по HTTPS.
  const note = document.getElementById('install-note');
  if (!window.isSecureContext && platform !== 'ios') {
    note.textContent = 'Сайт открыт по обычному http, поэтому браузер может не предложить ' +
      'установку. Ярлык на рабочий стол всё равно можно создать вручную, а для полноценной ' +
      'установки сайт нужно открыть по адресу https://';
    note.hidden = false;
  } else {
    note.hidden = true;
  }

  installModal.hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeInstallModal() {
  installModal.hidden = true;
  document.body.style.overflow = '';
}

installModal.addEventListener('click', (event) => {
  if (event.target.hasAttribute('data-close')) closeInstallModal();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !installModal.hidden) closeInstallModal();
});

document.getElementById('install-now').addEventListener('click', async () => {
  if (!installPrompt) return;
  const prompt = installPrompt;
  installPrompt = null;
  closeInstallModal();
  prompt.prompt();
  await prompt.userChoice;
});

window.addEventListener('appinstalled', () => { installPrompt = null; });

/* ------------------------------------------------------------ главная --- */

function renderHome() {
  App.root.replaceChildren(tpl('tpl-home'));

  const note = document.getElementById('home-note');
  if (App.meta) {
    note.textContent = App.meta.ready
      ? `Сейчас идёт ${App.meta.current_week}-я неделя`
      : 'Расписание не загрузилось — обновите страницу.';
  }

  fillRecent(document.getElementById('home-recent'), readRecent());
}

function fillRecent(box, items) {
  if (!box || !items.length) return;
  box.querySelector('.recent__items').replaceChildren(...items.map((item) => {
    const link = el('a', null, item.name);
    link.href = routeFor(item.kind, item.name);
    return link;
  }));
  box.hidden = false;
}

/* ------------------------------------------------------- выбор группы --- */

function renderPicker(kind) {
  App.root.replaceChildren(tpl('tpl-picker'));
  const isGroup = kind === 'group';
  const title = App.root.querySelector('.picker__title');
  const lead = App.root.querySelector('.picker__lead');
  const input = document.getElementById('search');
  const results = document.getElementById('results');

  title.textContent = isGroup ? 'Выберите группу' : 'Выберите преподавателя';
  lead.textContent = isGroup
    ? 'Начните вводить название группы или найдите её в списке ниже.'
    : 'Начните вводить фамилию или выберите из списка.';
  input.placeholder = isGroup ? 'Например: 2 ИСиП' : 'Например: Иванов';

  renderRecent(kind);

  const items = App.meta ? (isGroup ? App.meta.groups : App.meta.teachers) : [];

  const draw = () => {
    const query = normalize(input.value);
    const matched = query ? items.filter((name) => normalize(name).includes(query)) : items;
    results.replaceChildren(
      matched.length
        ? (isGroup ? groupedBySpeciality(matched) : groupedByLetter(matched))
        : el('div', 'empty', 'Ничего не найдено. Проверьте написание.')
    );
  };

  input.addEventListener('input', draw);
  draw();
  if (window.matchMedia('(min-width: 900px)').matches) input.focus();
}

function renderRecent(kind) {
  fillRecent(document.getElementById('recent'),
             readRecent().filter((item) => item.kind === kind));
}

function section(title, names) {
  const wrap = el('div', 'result-group');
  wrap.append(el('h2', 'result-group__title', title));
  const items = el('div', 'result-group__items');
  for (const name of names) {
    const link = el('a', 'pill', name);
    link.href = routeFor('group', name);
    items.append(link);
  }
  wrap.append(items);
  return wrap;
}

function groupedBySpeciality(names) {
  const buckets = new Map();
  for (const name of names) {
    const { speciality } = splitGroup(name);
    if (!buckets.has(speciality)) buckets.set(speciality, []);
    buckets.get(speciality).push(name);
  }
  const fragment = document.createDocumentFragment();
  for (const [speciality, groups] of [...buckets].sort((a, b) => a[0].localeCompare(b[0], 'ru'))) {
    groups.sort((a, b) =>
      splitGroup(a).course - splitGroup(b).course || a.localeCompare(b, 'ru', { numeric: true }));
    fragment.append(section(speciality, groups));
  }
  return fragment;
}

function groupedByLetter(names) {
  const buckets = new Map();
  for (const name of names) {
    const letter = name.charAt(0).toUpperCase();
    if (!buckets.has(letter)) buckets.set(letter, []);
    buckets.get(letter).push(name);
  }
  const fragment = document.createDocumentFragment();
  for (const [letter, people] of [...buckets].sort((a, b) => a[0].localeCompare(b[0], 'ru'))) {
    const wrap = el('div', 'result-group');
    wrap.append(el('h2', 'result-group__title', letter));
    const items = el('div', 'result-group__items');
    for (const person of people.sort((a, b) => a.localeCompare(b, 'ru'))) {
      const link = el('a', 'pill pill--wide', person);
      link.href = routeFor('teacher', person);
      items.append(link);
    }
    wrap.append(items);
    fragment.append(wrap);
  }
  return fragment;
}

/* --------------------------------------------------------- расписание --- */

async function renderSchedule(kind, name) {
  App.root.replaceChildren(tpl('tpl-schedule'));
  App.root.querySelector('.schedule__name').textContent = name;
  const backLink = document.getElementById('back-link');
  backLink.href = kind === 'group' ? '#/student' : '#/teacher';
  backLink.textContent = kind === 'group' ? '← К списку групп' : '← К списку преподавателей';

  pushRecent(kind, name);

  const tabs = [...App.root.querySelectorAll('.tab')];
  const weekpick = document.getElementById('weekpick');
  const days = document.getElementById('days');
  const shareButton = document.getElementById('share-btn');
  const shareText = shareButton.querySelector('.share__text');
  let shareDayData = null;
  let view = sessionStorage.getItem('umpk.view') || 'today';

  shareButton.addEventListener('click', async () => {
    if (!shareDayData || shareButton.disabled) return;
    shareButton.disabled = true;
    shareText.textContent = 'Готовим…';
    try {
      const how = await shareDay(shareDayData, name, kind);
      shareText.textContent = how === 'downloaded' ? 'Сохранено' : 'Поделиться';
    } catch (error) {
      shareText.textContent = 'Не вышло';
      console.error('Поделиться не получилось:', error);
    }
    setTimeout(() => { shareText.textContent = 'Поделиться'; shareButton.disabled = false; }, 2500);
  });

  const load = () => {
    const now = new Date();
    tabs.forEach((tab) => {
      if (tab.dataset.view === 'today') tab.textContent = dayLabel(now);
      if (tab.dataset.view === 'tomorrow') tab.textContent = dayLabel(addDays(now, 1));
    });
    tabs.forEach((tab) => tab.classList.toggle('is-active', tab.dataset.view === view));
    weekpick.hidden = view !== 'week';
    days.classList.toggle('days--single', view !== 'week');
    days.replaceChildren(el('div', 'loading', 'Загружаем расписание…'));

    const loadedOn = isoDate(now);
    let from = now;
    let count = 1;

    if (view === 'tomorrow') {
      from = addDays(now, 1);
    } else if (view === 'week') {
      // Выбирать можно только те недели, которые колледж выложил.
      const list = publishedWeeks();
      if (App.weekIndex === null) App.weekIndex = currentWeekIndex(list);
      App.weekIndex = Math.min(Math.max(App.weekIndex, 0), list.length - 1);
      from = new Date(list[App.weekIndex].monday + 'T00:00:00');
      count = 6;
      renderWeekPicker(weekpick, list, App.weekIndex, (index) => {
        App.weekIndex = index;
        load();
      });
    }

    try {
      const data = scheduleFor(kind, name, from, count);
      renderDays(days, data, view);

      // Картинкой отправляем один день: неделя вышла бы длинной простынёй,
      // которую в переписке всё равно не разглядеть.
      shareDayData = count === 1 && data.found ? data.days[0] : null;
      shareButton.hidden = !shareDayData;

      // Раз в минуту перерисовываем то же самое: меняются отметки
      // «идёт сейчас» и «пара прошла». А если страницу оставили открытой
      // до полуночи — перезапрашиваем: даты на вкладках уже другие.
      clearInterval(App.tick);
      App.tick = setInterval(() => {
        if (isoDate(new Date()) !== loadedOn) load();
        else renderDays(days, data, view);
      }, 60000);
    } catch (error) {
      clearInterval(App.tick);
      days.replaceChildren(el('div', 'empty', `Не удалось загрузить расписание: ${error.message}`));
    }
  };

  tabs.forEach((tab) => tab.addEventListener('click', () => {
    view = tab.dataset.view;
    if (view !== 'week') App.weekIndex = null;
    sessionStorage.setItem('umpk.view', view);
    load();
  }));

  load();
}

function renderWeekPicker(box, list, active, onPick) {
  box.replaceChildren(...list.map((item, index) => {
    const button = el('button', `weekpick__btn${index === active ? ' is-active' : ''}`);
    button.type = 'button';
    button.append(el('span', 'weekpick__name', `${item.week} неделя`));
    const dates = item.short || item.label;
    if (dates) button.append(el('span', 'weekpick__dates', dates));
    button.addEventListener('click', () => {
      if (index !== active) onPick(index);
    });
    return button;
  }));
}

function renderDays(container, data, view) {
  const todayIso = isoDate(new Date());
  const badge = document.getElementById('week-badge');
  if (badge && data.days.length) badge.textContent = `${data.days[0].week}-я неделя`;

  if (!data.found) {
    container.replaceChildren(el('div', 'empty',
      'Для этого имени расписание не найдено. Возможно, оно ещё не опубликовано.'));
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const day of data.days) {
    fragment.append(renderDay(day, day.date === todayIso, data.kind));
  }
  container.replaceChildren(fragment);

  if (view !== 'week' && !data.days.some((day) => day.lessons.length)) {
    container.append(el('div', 'empty', 'Свободный день — занятий нет.'));
  }
}

function renderDay(day, isToday, kind) {
  const card = el('article', `day${isToday ? ' day--today' : ''}`);
  const head = el('header', 'day__head');
  head.append(el('span', 'day__name', day.weekday_name));
  head.append(el('span', 'day__date', `${day.date_label} · ${day.week}-я неделя`));
  if (isToday) head.append(el('span', 'day__today', 'сегодня'));
  card.append(head);

  const removed = day.removed || [];
  if (!day.lessons.length && !removed.length) {
    card.append(el('div', 'day__empty',
      day.weekday === 7 ? 'Воскресенье — выходной' : 'Занятий нет'));
    return card;
  }

  const nowMinutes = isToday ? currentMinutes() : -1;
  for (const lesson of day.lessons) {
    card.append(renderLesson(lesson, nowMinutes, kind));
  }
  // Снятые пары показываем последними и зачёркнутыми: их уже нет в сетке,
  // но человеку важно увидеть, что занятие отменили.
  for (const lesson of removed) {
    card.append(renderLesson(lesson, -1, kind));
  }
  return card;
}

function currentMinutes() {
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
}

/** «08:30–09:15» -> [510, 555] в минутах от полуночи. */
function lessonRange(time) {
  const match = time.match(/(\d{1,2}):(\d{2}).(\d{1,2}):(\d{2})/);
  if (!match) return null;
  return [
    Number(match[1]) * 60 + Number(match[2]),
    Number(match[3]) * 60 + Number(match[4]),
  ];
}

/* ------------------------------------------------- картинка на день ---- */

/**
 * Рисует расписание дня картинкой, чтобы отправить в переписку.
 *
 * Рисуем сами на canvas, а не фотографируем страницу: так картинка выходит
 * одинаковой на всех устройствах и не тянет за собой стороннюю библиотеку.
 * Размер удваиваем — иначе на телефонах текст выйдет мыльным.
 */
function drawDay(day, title, kind) {
  const S = 2;                       // множитель чёткости
  const W = 720;                     // ширина картинки в «обычных» точках
  const PAD = 36;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const font = (size, weight = 400) =>
    `${weight} ${size}px -apple-system, "Segoe UI", Roboto, Arial, sans-serif`;

  const wrap = (text, maxWidth, size, weight) => {
    ctx.font = font(size, weight);
    const words = String(text).split(' ');
    const lines = [];
    let line = '';
    for (const word of words) {
      const next = line ? line + ' ' + word : word;
      if (ctx.measureText(next).width > maxWidth && line) {
        lines.push(line);
        line = word;
      } else {
        line = next;
      }
    }
    if (line) lines.push(line);
    return lines;
  };

  const lessons = [...day.lessons, ...(day.removed || [])];
  const textLeft = PAD + 96;
  const textWidth = W - textLeft - PAD;

  // Первый проход — считаем высоту, чтобы не резать содержимое.
  const MARK_TEXT = { new: 'новая', changed: 'изменилась', removed: 'снята' };
  const MARK_COLOR = { new: '#1f6e2b', changed: '#a35b00', removed: '#b3261e' };

  const rows = lessons.map((l) => {
    const subject = wrap(l.subject, textWidth, 21, 700);
    const meta = [
      kind === 'teacher' ? l.group : l.teacher,
      l.room && 'ауд. ' + l.room,
      l.subgroup && `${l.subgroup}-я подгруппа`,
    ].filter(Boolean).join('   ');
    const mark = MARK_TEXT[l.mark] || '';
    return {
      lesson: l, subject, meta, mark,
      markColor: MARK_COLOR[l.mark],
      height: subject.length * 27 + (meta || mark ? 26 : 4) + 22,
    };
  });

  const headHeight = 132;
  const footHeight = 54;
  const bodyHeight = rows.length
    ? rows.reduce((sum, r) => sum + r.height, 0)
    : 70;
  const H = headHeight + bodyHeight + footHeight;

  canvas.width = W * S;
  canvas.height = H * S;
  ctx.scale(S, S);

  // Фон и шапка — всегда светлые: картинку смотрят в чужой переписке.
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = '#1a4ed0';
  ctx.fillRect(0, 0, W, 8);

  ctx.fillStyle = '#17233c';
  ctx.font = font(30, 800);
  ctx.fillText(title, PAD, 62);

  ctx.fillStyle = '#41506d';
  ctx.font = font(19);
  ctx.fillText(`${day.weekday_name}, ${day.date_label} · ${day.week}-я неделя`, PAD, 94);

  ctx.strokeStyle = '#e3e8f2';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD, 114);
  ctx.lineTo(W - PAD, 114);
  ctx.stroke();

  let y = headHeight;
  if (!rows.length) {
    ctx.fillStyle = '#7b88a1';
    ctx.font = font(20);
    ctx.fillText(day.weekday === 7 ? 'Воскресенье — выходной' : 'Занятий нет', PAD, y + 20);
  }

  for (const row of rows) {
    const [start, end] = row.lesson.time.split(/[-–—]/).map((p) => p.trim());
    const faded = row.lesson.mark === 'removed';

    ctx.fillStyle = faded ? '#7b88a1' : '#17233c';
    ctx.font = font(21, 700);
    ctx.fillText(start, PAD, y + 21);
    ctx.fillStyle = '#7b88a1';
    ctx.font = font(17);
    if (end) ctx.fillText(end, PAD, y + 44);

    ctx.fillStyle = faded ? '#7b88a1' : '#17233c';
    ctx.font = font(21, 700);
    let ty = y + 21;
    for (const line of row.subject) {
      ctx.fillText(line, textLeft, ty);
      if (faded) {                    // зачёркиваем снятую пару
        const w = ctx.measureText(line).width;
        ctx.fillRect(textLeft, ty - 7, w, 1.5);
      }
      ty += 27;
    }

    if (row.meta || row.mark) {
      ctx.font = font(17);
      let mx = textLeft;
      if (row.meta) {
        ctx.fillStyle = '#41506d';
        ctx.fillText(row.meta, mx, ty + 2);
        mx += ctx.measureText(row.meta).width + 16;
      }
      if (row.mark) {                 // отметку красим, иначе теряется в сером
        ctx.fillStyle = row.markColor;
        ctx.font = font(17, 700);
        ctx.fillText(row.mark, mx, ty + 2);
      }
    }

    y += row.height;
    ctx.strokeStyle = '#eef1f7';
    ctx.beginPath();
    ctx.moveTo(PAD, y - 11);
    ctx.lineTo(W - PAD, y - 11);
    ctx.stroke();
  }

  ctx.fillStyle = '#7b88a1';
  ctx.font = font(16);
  ctx.fillText('umpksch.ru · расписание УМПК', PAD, H - 22);

  return canvas;
}

/** Отдаёт картинку в системное «Поделиться», а где его нет — просто скачивает. */
async function shareDay(day, title, kind) {
  const canvas = drawDay(day, title, kind);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
  if (!blob) throw new Error('не удалось нарисовать картинку');

  const safe = `${title} ${day.date}`.replace(/[^\wа-яёА-ЯЁ\- ]+/gi, '').trim();
  const file = new File([blob], `${safe}.png`, { type: 'image/png' });

  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: `${title} — ${day.date_label}` });
      return 'shared';
    } catch (error) {
      if (error && error.name === 'AbortError') return 'cancelled';   // человек закрыл окно
      // Не получилось поделиться — уходим на скачивание.
    }
  }

  const url = URL.createObjectURL(blob);
  const link = el('a');
  link.href = url;
  link.download = file.name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  return 'downloaded';
}

const MARKS = {
  new: { text: 'новая', cls: 'badge--new' },
  changed: { text: 'изменилась', cls: 'badge--changed' },
  removed: { text: 'снята', cls: 'badge--removed' },
};

function renderLesson(lesson, nowMinutes, kind) {
  // nowMinutes < 0 — день не сегодняшний, отмечать нечего.
  const range = lessonRange(lesson.time);
  const gone = lesson.mark === 'removed';
  const isNow = !gone && range && nowMinutes >= range[0] && nowMinutes <= range[1];
  const isDone = !gone && range && nowMinutes >= 0 && nowMinutes > range[1];

  const row = el('div', `lesson${isNow ? ' lesson--now' : ''}`
    + `${isDone ? ' lesson--done' : ''}${gone ? ' lesson--removed' : ''}`);

  const [start, end] = lesson.time.split(/[-–—]/).map((part) => part.trim());
  const slot = el('div', 'lesson__slot');
  slot.append(el('span', 'lesson__start', start));
  if (end) slot.append(el('span', 'lesson__end', end));
  if (lesson.pair) slot.append(el('span', 'lesson__pair', `${lesson.pair} урок`));
  row.append(slot);

  const body = el('div');
  body.append(el('div', 'lesson__subject', lesson.subject));

  const meta = el('div', 'lesson__meta');
  if (kind === 'teacher') meta.append(el('span', 'lesson__group', lesson.group));
  if (lesson.teacher && kind !== 'teacher') meta.append(el('span', 'lesson__teacher', lesson.teacher));
  if (lesson.room) meta.append(el('span', 'lesson__room', lesson.room));
  if (lesson.subgroup) meta.append(el('span', 'badge badge--sub', `${lesson.subgroup}-я подгруппа`));
  if (lesson.note) meta.append(el('span', 'badge badge--note', lesson.note));

  const mark = MARKS[lesson.mark];
  if (mark) {
    const badge = el('span', `badge ${mark.cls}`, mark.text);
    if (lesson.mark_on) {
      const when = new Date(lesson.mark_on + 'T00:00:00');
      badge.title = `${mark.text} ${dayLabel(when)}`;
    }
    meta.append(badge);
  }
  if (meta.childNodes.length) body.append(meta);

  row.append(body);
  return row;
}

/* --------------------------------------------------------------- инфо --- */

function renderInfo() {
  App.root.replaceChildren(tpl('tpl-info'));
  const body = document.getElementById('info-body');
  const meta = App.meta;
  if (!meta) {
    body.append(el('div', 'empty', 'Расписание не загрузилось. Обновите страницу.'));
    return;
  }

  const about = el('div', 'info__block');
  about.append(el('h2', null, 'Откуда берутся данные'));
  about.append(el('p', null,
    'Раз в час GitHub Actions скачивает таблицы расписания из публичной папки облака ' +
    'колледжа, разбирает их и обновляет файл, который читает сайт. Сервер для этого не нужен.'));
  if (meta.weeks && meta.weeks.length) {
    const weeks = meta.weeks.map((w) => `${w.label} (${w.week}-я)`).join(', ');
    about.append(el('p', null,
      `Листать можно по неделям, у которых в таблицах проставлены даты: ${weeks}.`));
  }
  const list = el('dl');
  const rows = [
    ['Расписание собрано', meta.built_on
      ? new Date(meta.built_on + 'T00:00:00').toLocaleDateString('ru-RU') : '—'],
    ['Периодичность', 'раз в час'],
    ['Групп', String(meta.groups.length)],
    ['Преподавателей', String(meta.teachers.length)],
    ['Текущая неделя', `${meta.current_week}-я`],
    ['Отсчёт чётности', meta.anchor_monday],
  ];
  for (const [term, value] of rows) {
    list.append(el('dt', null, term), el('dd', null, value));
  }
  about.append(list);
  body.append(about);

  if (meta.files && meta.files.length) {
    const files = el('div', 'info__block');
    files.append(el('h2', null, 'Файлы расписания'));
    const items = el('ul');
    for (const file of meta.files) {
      items.append(el('li', null,
        `${file.name} — ${file.groups} групп, ${file.lessons} занятий ` +
        `(изменён ${new Date(file.mtime).toLocaleString('ru-RU')})`));
    }
    files.append(items);
    body.append(files);
  }

  if (meta.warnings && meta.warnings.length) {
    const warn = el('div', 'info__block');
    warn.append(el('h2', null, 'Замечания к исходным таблицам'));
    const items = el('ul', 'warnings');
    for (const message of meta.warnings) items.append(el('li', null, message));
    warn.append(items);
    body.append(warn);
  }

}

/* ---------------------------------------------------------- маршруты ---- */

async function route() {
  const hash = location.hash.replace(/^#/, '') || '/';
  const parts = hash.split('/').filter(Boolean);
  window.scrollTo(0, 0);
  clearInterval(App.tick);

  if (!parts.length) return renderHome();
  switch (parts[0]) {
    case 'student': return renderPicker('group');
    case 'teacher': return renderPicker('teacher');
    case 'info': return renderInfo();
    case 'g': return renderSchedule('group', decodeURIComponent(parts[1] || ''));
    case 't': return renderSchedule('teacher', decodeURIComponent(parts[1] || ''));
    default: return renderHome();
  }
}

function updateFooter() {
  const line = document.getElementById('footer-meta');
  if (!App.meta) { line.textContent = 'Не удалось загрузить расписание.'; return; }
  line.textContent = App.meta.built_on
    ? `Расписание от ${new Date(App.meta.built_on + 'T00:00:00').toLocaleDateString('ru-RU')}`
    : '';
}

async function start() {
  App.root.replaceChildren(el('div', 'loading', 'Загружаем расписание…'));
  try {
    App.data = await loadData();
    App.meta = {
      ready: true,
      groups: App.data.groups,
      teachers: App.data.teachers,
      current_week: weekNumber(new Date()),
      built_on: App.data.built_on,
      anchor_monday: App.data.anchor_monday,
      files: App.data.files,
      warnings: App.data.warnings,
    };
  } catch (error) {
    App.data = null;
    App.meta = null;
    console.error('Не удалось прочитать', DATA_URL, error);
  }
  updateFooter();
  window.addEventListener('hashchange', route);
  await route();
}

// Нужен для установки сайта как приложения и для работы без сети.
// Браузеры разрешают service worker только на localhost или по HTTPS.
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => { /* не критично */ });
  });
}

start();
