# StreamSwitcher как замена RadioBoss — полный анализ и роадмап

> Документ описывает **текущее состояние** проекта `StreamSwitcher`,
> **gap-анализ** относительно [RadioBoss](https://www.djsoft.net/radioboss.htm)
> и **подробный план развития** (фичи, архитектура, тесты, CI).
>
> Версия документа: v1.0 · Целевая аудитория: разработчики, мейнтейнеры,
> ревьюеры PR.

---

## Оглавление

1. [Что такое RadioBoss и зачем повторять](#1-что-такое-radioboss-и-зачем-повторять)
2. [Текущее состояние StreamSwitcher](#2-текущее-состояние-streamswitcher)
3. [Gap-анализ: RadioBoss vs StreamSwitcher](#3-gap-анализ-radioboss-vs-streamswitcher)
4. [Архитектурный план](#4-архитектурный-план)
5. [Roadmap по фазам](#5-roadmap-по-фазам)
6. [Детальные спецификации фич](#6-детальные-спецификации-фич)
7. [План тестирования](#7-план-тестирования)
8. [CI / CD / Качество кода](#8-ci--cd--качество-кода)
9. [Definition of Done](#9-definition-of-done)

---

## 1. Что такое RadioBoss и зачем повторять

**RadioBoss** — это коммерческое профессиональное ПО для автоматизации
радиовещания. Ключевые возможности, на которые мы ориентируемся:

| Группа | Возможности RadioBoss |
|--------|-----------------------|
| **Плейлисты** | Drag-n-Drop, M3U/PLS/ASX/XSPF импорт-экспорт, теги ID3v1/v2, обложки, BPM, key, smart-playlists, фильтры |
| **Воспроизведение** | Два движка (двойной плеер), кроссфейд, gapless, mix-точки, cue, оверлап, AGC, нормализация |
| **Sources** | Live in (microphone), Line-In, файлы, интернет-радио, video (audio track) |
| **DSP** | 18-полосный EQ, компрессор, лимитер, ducking ("ведущий поверх музыки"), bass boost, normalize |
| **Streaming** | Icecast, Shoutcast, multi-encoder, MP3/AAC/Ogg, перезапуск, история, статистика |
| **Запись эфира** | Continuous recording (logger), split по времени, MP3/WAV |
| **Автоматизация** | Расписание (events), rotation policies, jingles, ads, weather, time announcements, news |
| **Плагины** | DSP plugins, VST, scripting (на собственном языке) |
| **Remote** | Web interface, REST API, мобильный UI |
| **AutoDJ** | Auto-rotation, smart shuffle, по жанру, по году, по тегам, бан-листы |
| **Кодеки** | MP3 (lame), AAC, AAC+, Ogg Vorbis, Opus, FLAC |
| **Сеть** | SMB, NFS, FTP, WebDAV, HTTP, Icecast statistics |
| **Audit / Logs** | Лог отыгранных треков, экспорт в CSV/XML, статистика прослушиваний |

**Наш план:** реализовать ~80% этих возможностей в open-source форме на Python +
PySide6 + sounddevice. Мы НЕ нацелены на VST-плагины и продвинутую видео-логику
(они выходят за рамки разумной сложности для первой версии).

---

## 2. Текущее состояние StreamSwitcher

### 2.1 Структура репозитория

```
StreamSwitcher/
├── main.py                  # Qt entry point
├── requirements.txt         # PySide6, sounddevice, soundfile, numpy, flask, scipy, mutagen
├── core/
│   ├── audio_engine.py      # 470 LOC — захват/микс/DSP/вывод, dual mix, failover
│   ├── source_manager.py    # 431 LOC — MP3/радио, плейлист, декодирование
│   ├── scheduler.py         # 127 LOC — расписание HH:MM:SS
│   ├── streamer.py          # 206 LOC — Icecast SOURCE-протокол
│   └── remote_api.py        # 250 LOC — Flask REST + HTML-пульт
└── ui/
    ├── main_window.py       # 958 LOC — основное окно (вкладки, top bar, левая панель)
    ├── styles.py            # 325 LOC — dark mode stylesheet
    ├── vu_meter.py          # 135 LOC — стерео VU + peak hold + clip
    ├── waveform_widget.py   # 103 LOC — мини-плеер с волной
    ├── dsp_panel.py         # 138 LOC — 5-полосный EQ + компрессор
    ├── scheduler_panel.py   # 259 LOC — UI расписания
    └── stream_panel.py      # 128 LOC — UI Icecast стриминга
```

Всего ~3500 LOC чистого кода. Тестов **нет**. CI **нет**.
`pyproject.toml` **нет**.

### 2.2 Что уже работает

- **Switching**: Live ↔ MP3 ↔ Radio с плавным fade-out/fade-in 1 сек.
- **Dual Mix**: live + MP3 или live + radio с независимыми громкостями.
- **Auto-Failover**: при тишине >8 сек на источнике — автопереключение по цепочке.
- **Silence detection**: на живом входе срабатывает через 30 сек тишины.
- **DSP**: 5-полосный peaking EQ (60/250/1000/4000/12000 Hz, ±12 dB) и простой
  feed-forward компрессор/лимитер. Включаются независимо.
- **Плейлист**: локальные файлы, HTTP, SMB/UNC; drag-and-drop перестановка;
  next track авто после конца.
- **Радио**: HTTP/Icecast потоки, кнопка "слушать", пресеты, индикатор буферизации.
- **Расписание**: HH:MM:SS, действия `play_file/play_radio/switch_live/stop`,
  daily repeat, редактирование по двойному клику.
- **Стриминг**: Icecast SOURCE, опциональный MP3-энкодер (lameenc), auto-reconnect,
  Icecast admin stats (listener count).
- **Remote API**: Flask на :8080, JSON `/api/status|control|source`, HTML-пульт
  для смартфона.
- **VU-метры**: стерео RMS + peak hold + clip indicator (-60..0 dBFS).
- **Waveform mini-player**: визуализация и click-to-seek.
- **Dark mode**: единый stylesheet через `ui/styles.py`.

### 2.3 Слабые места / технический долг

| # | Проблема | Влияние |
|---|----------|---------|
| 1 | Нет персистентности — все настройки, плейлист, пресеты, EQ теряются при перезапуске | High |
| 2 | Нет тестов — невозможно безопасно рефакторить | High |
| 3 | Нет CI — регрессии не ловятся | High |
| 4 | DSP-логика смешана с потоками `sounddevice` → сложно тестировать без аудио-устройств | Medium |
| 5 | `EQ` использует выходной сигнал текущего блока как RMS reference (некорректно для коротких блоков) | Medium |
| 6 | Компрессор работает по блочному RMS — нет attack/release | Medium |
| 7 | Радиопоток "декодируется" через `soundfile.read(BytesIO(buf))` — это работает только для container-форматов (Ogg), но не для голого MP3-потока. Нужен потоковый декодер (`pydub`/`miniaudio`/`ffmpeg`) | High |
| 8 | Icecast streamer всегда отправляет PCM, если нет `lameenc` — большинство Icecast серверов это отвергнут | High |
| 9 | Кроссфейд между треками отсутствует — gap между концом одного и началом следующего | High |
| 10 | Remote API без аутентификации — любой в локальной сети может управлять станцией | Medium |
| 11 | Нет логирования эфира (play history) | Medium |
| 12 | Mutagen есть в зависимостях, но не используется (ID3-теги не читаются) | Low |
| 13 | `schedule` (PyPI) в requirements, но не используется (планировщик написан вручную) | Low |
| 14 | Нет hot-reload устройств при их подключении | Low |
| 15 | Нет горячих клавиш | Low |
| 16 | Нет записи эфира в файл | Medium |
| 17 | Нет AutoDJ / правил ротации | Medium |
| 18 | `MainWindow.__init__` запускает `engine.start()` — на headless среде падает | Medium |

---

## 3. Gap-анализ: RadioBoss vs StreamSwitcher

Легенда: ✅ есть · 🟡 частично · ❌ нет · 🚫 не планируем

| Категория | RadioBoss | StreamSwitcher | Приоритет |
|-----------|-----------|----------------|-----------|
| **Плейлист — drag & drop** | ✅ | ✅ | — |
| **Плейлист — M3U/PLS/XSPF импорт** | ✅ | ❌ | P0 |
| **Плейлист — M3U/PLS экспорт** | ✅ | ❌ | P0 |
| **ID3-теги (artist, title, album, BPM)** | ✅ | ❌ (mutagen есть, но не подключен) | P0 |
| **Smart playlists (фильтры)** | ✅ | ❌ | P2 |
| **AutoDJ / Rotation rules** | ✅ | ❌ | P1 |
| **Jingles / Ads / Spots** | ✅ | ❌ (можно эмулировать расписанием) | P1 |
| **Cue-точки / mix-точки** | ✅ | ❌ | P2 |
| **Кроссфейд между треками** | ✅ | ❌ | P0 |
| **Gapless playback** | ✅ | 🟡 (auto-next, но через декод-паузу) | P1 |
| **Fade-in/Fade-out источников** | ✅ | ✅ (1 сек) | — |
| **Ducking ("ведущий поверх музыки")** | ✅ | 🟡 (есть Dual Mix, но без auto-duck) | P1 |
| **Live input** | ✅ | ✅ | — |
| **Multiple inputs (несколько каналов)** | ✅ | ❌ | P2 |
| **Internet radio как источник** | ✅ | 🟡 (декодер работает только для Ogg-контейнера) | P0 |
| **Запись эфира (logger)** | ✅ | ❌ | P1 |
| **Split-recording по времени** | ✅ | ❌ | P2 |
| **EQ (10+ полос)** | ✅ 18 | 🟡 5 полос | P1 |
| **Compressor / Limiter с attack/release** | ✅ | 🟡 (без attack/release) | P1 |
| **Normalize / AGC** | ✅ | ❌ | P1 |
| **Bass / Treble enhancer** | ✅ | ❌ | P2 |
| **VST plugins** | ✅ | 🚫 | — |
| **Icecast streaming (MP3)** | ✅ | 🟡 (нужен `lameenc`) | P0 |
| **Shoutcast streaming** | ✅ | 🟡 (тот же путь, но HTTP/1.0 — работает не везде) | P1 |
| **AAC/AAC+ encoding** | ✅ | ❌ | P2 |
| **Ogg/Opus encoding** | ✅ | ❌ | P2 |
| **Multi-encoder (несколько кодировок одновременно)** | ✅ | ❌ | P2 |
| **Auto-reconnect Icecast** | ✅ | ✅ | — |
| **Listener count** | ✅ | ✅ | — |
| **Расписание событий (HH:MM:SS)** | ✅ | ✅ | — |
| **Day-of-week / повтор по дням недели** | ✅ | 🟡 (только daily/once) | P1 |
| **Hourly / interval events** | ✅ | ❌ | P1 |
| **One-shot events** | ✅ | ✅ | — |
| **Time announcements (TTS)** | ✅ | ❌ | P2 |
| **Weather / News autoplay** | ✅ | ❌ | P2 |
| **VU meters (stereo)** | ✅ | ✅ | — |
| **Spectrum analyzer** | ✅ | ❌ | P2 |
| **Waveform mini-player** | ✅ | ✅ | — |
| **Persistence: settings / playlist / schedule** | ✅ | ❌ | **P0** |
| **History log (что играло, когда)** | ✅ | ❌ | P1 |
| **Hotkeys** | ✅ | ❌ | P1 |
| **Remote API (REST)** | ✅ | 🟡 (минимальный) | P1 |
| **Web UI (расширенный)** | ✅ | 🟡 (только base controls) | P1 |
| **API authentication** | ✅ | ❌ | P0 |
| **Multi-language UI** | ✅ | ❌ | P2 |
| **CLI / headless mode** | ✅ | ❌ | P1 |
| **Scripting** | ✅ (свой DSL) | ❌ | P3 |

---

## 4. Архитектурный план

### 4.1 Принципы

1. **Чистые модули → тестируемость**.
   Логика DSP, fade-расчётов, плейлиста, расписания и стриминга должна быть
   **отделена** от I/O (sounddevice, requests, Flask, PySide6). I/O — это
   "адаптеры" поверх pure-logic.
2. **Конфигурация — single source of truth**.
   Один `Config` (Pydantic-стиль dataclass) грузится на старте и сохраняется
   при выходе. Все панели UI читают/пишут в неё.
3. **Event bus**.
   Постепенный переход с прямых Qt-сигналов на единый `EventBus`, чтобы
   облегчить тестирование и интеграцию с CLI/headless режимом.
4. **Backward-compat**.
   Все существующие пользовательские workflows (UI-кнопки, Remote API,
   расписание) продолжают работать без перекомпиляции конфигов.

### 4.2 Новый layout

```
StreamSwitcher/
├── core/
│   ├── audio_engine.py
│   ├── source_manager.py
│   ├── scheduler.py
│   ├── streamer.py
│   ├── remote_api.py
│   ├── config.py            # NEW — persistence (JSON)
│   ├── dsp.py               # NEW — чистый EQ/comp/limiter math (pure numpy)
│   ├── playlist.py          # NEW — M3U/PLS импорт/экспорт + ID3 теги
│   ├── crossfade.py         # NEW — расчёт кривых кроссфейда
│   ├── recorder.py          # NEW — запись эфира в WAV/MP3
│   ├── autodj.py            # NEW — правила ротации
│   └── history.py           # NEW — лог отыгранных треков
├── ui/
│   ├── ...                  # как сейчас
│   └── library_panel.py     # NEW — поиск/фильтры по тегам
├── tests/
│   ├── conftest.py
│   ├── test_dsp.py
│   ├── test_playlist.py
│   ├── test_scheduler.py
│   ├── test_crossfade.py
│   ├── test_config.py
│   ├── test_streamer_handshake.py
│   ├── test_remote_api.py
│   └── test_source_manager.py
├── docs/
│   ├── RADIOBOSS_REPLACEMENT_ROADMAP.md   # этот файл
│   └── ARCHITECTURE.md                     # последует
├── .github/workflows/ci.yml
├── pyproject.toml
└── README.md
```

### 4.3 Подмодуль `core/dsp.py`

Чистые функции без I/O:

```python
def apply_peaking_eq(audio: np.ndarray, sr: int,
                     bands: dict[int, float]) -> np.ndarray: ...

def apply_compressor(audio: np.ndarray, sr: int,
                     threshold_db: float, ratio: float,
                     attack_ms: float, release_ms: float,
                     makeup_db: float) -> np.ndarray: ...

def apply_limiter(audio: np.ndarray, ceiling_db: float = -0.3) -> np.ndarray: ...

def fade_curve(steps: int, curve: str = "equal_power") -> np.ndarray: ...

def crossfade(a: np.ndarray, b: np.ndarray, frames: int) -> np.ndarray: ...
```

Это позволит писать **юнит-тесты на математику** без запуска `sd.OutputStream`.

### 4.4 Подмодуль `core/config.py`

Pydantic-стиль dataclass с JSON-сериализацией:

```python
@dataclass
class AppConfig:
    sample_rate: int = 44100
    input_device: Optional[int] = None
    output_device: Optional[int] = None
    master_volume: float = 0.8
    eq_bands: dict[int, float] = field(default_factory=lambda: {60: 0, 250: 0, ...})
    eq_enabled: bool = False
    compressor: CompressorConfig = field(default_factory=CompressorConfig)
    playlist: list[str] = field(default_factory=list)
    radio_presets: list[RadioPreset] = field(default_factory=list)
    radio_url: str = ""
    schedule: list[ScheduleEntryDict] = field(default_factory=list)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    remote_api_key: str = ""
    autodj: AutoDJConfig = field(default_factory=AutoDJConfig)
    crossfade_seconds: float = 3.0
    hotkeys: dict[str, str] = field(default_factory=dict)
```

Файл хранится в:
- Linux/macOS: `~/.config/streamswitcher/config.json`
- Windows: `%APPDATA%\StreamSwitcher\config.json`

### 4.5 Подмодуль `core/playlist.py`

```python
class Track:
    path: str
    title: str
    artist: str
    album: str
    duration: float
    bitrate: int
    tags: dict[str, str]

def parse_m3u(content: str) -> list[Track]: ...
def parse_pls(content: str) -> list[Track]: ...
def write_m3u(tracks: list[Track]) -> str: ...
def write_pls(tracks: list[Track]) -> str: ...
def read_tags(path: str) -> dict[str, str]: ...   # через mutagen
```

### 4.6 Подмодуль `core/crossfade.py`

```python
@dataclass
class CrossfadeState:
    duration_sec: float = 3.0
    curve: str = "equal_power"   # linear, equal_power, exponential
    enabled: bool = True

def equal_power_curve(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Returns (fade_out_a, fade_in_b) arrays of length n."""
```

### 4.7 Подмодуль `core/history.py`

```python
@dataclass
class HistoryEntry:
    timestamp: datetime
    source: str
    track: str
    duration: float
    listeners: int

class HistoryLog:
    def append(self, entry: HistoryEntry): ...
    def get_range(self, start: datetime, end: datetime) -> list[HistoryEntry]: ...
    def export_csv(self, path: str): ...
```

### 4.8 Подмодуль `core/recorder.py`

```python
class AirRecorder:
    """Continuous recording of the broadcast output to WAV/MP3 files,
    automatically splitting by time interval."""
    def start(self, output_dir: str, split_minutes: int = 60,
              format: Literal["wav", "mp3"] = "wav"): ...
    def push_audio(self, audio: np.ndarray): ...
    def stop(self): ...
```

### 4.9 Аутентификация Remote API

- Простой Bearer-token из конфигурации (`remote_api_key`).
- Если ключ пуст — API публичный (для совместимости с текущим поведением).
- Если задан — все `/api/*` маршруты требуют заголовок `Authorization: Bearer <key>`.

---

## 5. Roadmap по фазам

### Фаза 0 — Foundation (этот PR)

Цель: безопасный фундамент для всех остальных фаз.

- [x] `pyproject.toml` (PEP 621), `ruff`, `pytest`.
- [x] GitHub Actions CI: lint + unit-tests на Python 3.10/3.11/3.12.
- [x] `tests/` каталог + конфтест + 6 первых suite'ов.
- [x] `core/config.py` — персистентность.
- [x] `core/dsp.py` — чистые DSP-функции (extract из engine).
- [x] `core/playlist.py` — M3U/PLS/ID3.
- [x] `core/crossfade.py` — кривые fade/crossfade.
- [x] `core/history.py` — log отыгранных треков.
- [x] `docs/RADIOBOSS_REPLACEMENT_ROADMAP.md` (этот файл).
- [x] Remote API: опциональный API key + `/api/playlist`, `/api/volume`,
      `/api/history`, `/api/eq`.

**Что НЕ ломаем:** существующие UI-флоу, Icecast-streamer, расписание.

### Фаза 1 — UX + Core фичи

- [ ] Crossfade UI (слайдер длительности в DSP-вкладке).
- [x] `core/autodj.py` + AutoDJ rules (next-track picker, jingle insertion, repeat-avoid).
- [x] `core/recorder.py` — Air Recorder с WAV-split (`split_minutes`).
- [x] `core/history.py` подключён к UI: `_on_track_changed` пишет в `HistoryLog`.
- [x] `core.playlist` M3U/PLS импорт/экспорт через UI (`📂 Импорт`, `💾 Экспорт`).
- [x] ID3-теги в плейлисте: отображается `Artist — Title` вместо `basename`.
- [x] `AppConfig` подключён к `MainWindow`: load on start, save on close, `Ctrl+S` save now.
- [x] Расписание: day-of-week + interval events (`weekdays`, `interval_seconds`).
- [x] Hotkeys: Space=Play/Stop, M=Mute, Ctrl+1/2/3=источники, Ctrl+N / →=Next, Ctrl+S=Save.
- [x] CLI mode (`python main.py --headless --config ... --port ... --api-key ...`).
- [ ] AutoDJ UI-вкладка (rules editor + history viewer).
- [ ] Air Recorder UI-вкладка (Start/Stop + список файлов).
- [ ] Перенос декодинга радио на `miniaudio` или `pydub` для нормальной поддержки
      MP3-потока.
- [ ] AGC / Normalize в DSP.

### Фаза 2 — Pro фичи

- [ ] 10-полосный EQ + графический dragger.
- [ ] Compressor с attack/release и lookahead-лимитером.
- [ ] Ducking (auto-attenuate music when mic is active).
- [ ] Multi-encoder streaming (mp3 + ogg одновременно).
- [ ] Spectrum analyzer.
- [ ] Web UI v2 (полный пульт с плейлистом, EQ, расписанием).
- [ ] Smart playlists с фильтрами по тегам.
- [ ] Cue points / mix points в треках.
- [ ] Multi-language UI (RU/EN/UK).

### Фаза 3 — Extensions

- [ ] Plugin API (Python-плагины для DSP).
- [ ] Weather / Time-of-day TTS announcements.
- [ ] Опциональная транскрипция эфира (Whisper).
- [ ] Multi-station deployments.

---

## 6. Детальные спецификации фич

### 6.1 Crossfade

**User story:** "Когда заканчивается трек A, начинается трек B так, чтобы
последние 3 секунды A плавно затихали, а первые 3 секунды B плавно нарастали,
без паузы между ними."

**Алгоритм (equal-power):**

```
gain_out[i] = cos(0.5 * π * i / N)
gain_in[i]  = sin(0.5 * π * i / N)
```

где `N` — число фреймов кроссфейда (`duration_sec * sample_rate`).

**Реализация:** `SourceManager` должен предзагрузить следующий трек за `N`
фреймов до конца текущего, и в `_get_file_frame` для последних `N` фреймов
выдавать микс `A * gain_out + B * gain_in`. После окончания микса
переключиться на B.

**Настройки:**
- Длительность: 0..15 сек (0 = выключен).
- Кривая: linear / equal_power / exponential.

### 6.2 M3U / PLS импорт-экспорт

**M3U формат:**
```
#EXTM3U
#EXTINF:217,Artist - Title
/path/to/file.mp3
http://example.com/stream
```

**PLS формат:**
```
[playlist]
File1=/path/file.mp3
Title1=Title
Length1=217
NumberOfEntries=1
Version=2
```

**API:** `Playlist.load_m3u(path)`, `Playlist.save_m3u(path)`, аналогично для PLS.

### 6.3 ID3-теги

Через `mutagen`:

```python
from mutagen import File
audio = File(path)
title = audio.get("TIT2") or audio.get("title")
artist = audio.get("TPE1") or audio.get("artist")
duration = audio.info.length
bitrate = audio.info.bitrate
```

UI отображает `Artist — Title` в плейлисте вместо имени файла.

### 6.4 AutoDJ

```python
@dataclass
class AutoDJRules:
    enabled: bool = False
    shuffle: bool = True
    repeat: Literal["off", "one", "all"] = "all"
    avoid_repeat_minutes: int = 30   # не повторять трек чаще
    crossfade_seconds: float = 3.0
    insert_jingle_every: int = 0     # 0 = без джинглов
    jingle_paths: list[str] = field(default_factory=list)
```

### 6.5 Air Recorder

- Подписывается на `AudioEngine._stream_output_callback` (тот же сигнал что и
  Icecast streamer).
- Пишет в `wav` (`soundfile.SoundFile` append mode).
- Каждые `split_minutes` закрывает файл и открывает новый с timestamp:
  `air_2026-05-13_14-00-00.wav`.

### 6.6 Remote API расширения

| Endpoint | Method | Описание |
|----------|--------|----------|
| `/api/status` | GET | Текущий статус (как сейчас) |
| `/api/control` | POST | play/stop/next/mute (как сейчас) |
| `/api/source` | POST | switch (как сейчас) |
| `/api/playlist` | GET | Получить плейлист |
| `/api/playlist` | POST | Загрузить плейлист |
| `/api/playlist/add` | POST | Добавить трек |
| `/api/playlist/remove` | POST | Удалить трек |
| `/api/volume` | POST | `{"master": 0.8}` |
| `/api/eq` | GET/POST | Состояние EQ |
| `/api/history` | GET | Последние N треков |
| `/api/schedule` | GET/POST | CRUD расписания |
| `/api/dual_mix` | POST | toggle + volumes |

Все защищены опциональным Bearer-токеном (см. §4.9).

### 6.7 Hotkeys

| Клавиша | Действие |
|---------|----------|
| `Space` | Play/Stop |
| `M` | Mute |
| `→` / `Ctrl+N` | Next track |
| `←` | Prev track |
| `Ctrl+1` | Live |
| `Ctrl+2` | MP3 |
| `Ctrl+3` | Radio |
| `Ctrl+D` | Dual Mix toggle |
| `Ctrl+S` | Save config |

### 6.8 CLI / Headless mode

```bash
python main.py --headless --config /etc/streamswitcher/config.json --port 8080
```

Без Qt main loop, только `AudioEngine` + `SourceManager` + `RemoteAPI` +
`Scheduler`. Управление через REST API.

---

## 7. План тестирования

### 7.1 Уровни тестов

| Уровень | Покрытие | Инструмент |
|---------|----------|------------|
| **Unit** | DSP-математика, playlist parse/serialize, schedule logic, config I/O, crossfade curves | pytest + numpy.testing |
| **Integration** | Streamer SOURCE handshake (mock сервер), Remote API endpoints (Flask test client) | pytest + Flask test client + httpretty |
| **System (Qt)** | Smoke: окно открывается, переключение источников, расписание срабатывает | pytest-qt (offscreen платформа) |
| **Manual** | Звук реально идёт в Icecast + микрофон + сеть | вручную |

### 7.2 Фикстуры

`tests/conftest.py`:

```python
@pytest.fixture
def silent_audio_block():
    return np.zeros((1024, 2), dtype=np.float32)

@pytest.fixture
def sine_audio_block(sr=44100, freq=440, frames=1024):
    t = np.arange(frames) / sr
    sig = np.sin(2 * np.pi * freq * t).astype(np.float32)
    return np.column_stack([sig, sig])

@pytest.fixture
def tmp_config_path(tmp_path):
    return tmp_path / "config.json"
```

### 7.3 Test suites (Фаза 0)

1. **`test_dsp.py`** — EQ, compressor, limiter, fade curves, crossfade.
2. **`test_playlist.py`** — M3U/PLS parse/serialize round-trip, ID3 extraction
   (mock mutagen).
3. **`test_scheduler.py`** — добавление/удаление/триггер событий,
   `compute_next`.
4. **`test_crossfade.py`** — equal-power кривая, gain-sum invariant.
5. **`test_config.py`** — JSON round-trip, default values, миграция версий.
6. **`test_streamer_handshake.py`** — Icecast `SOURCE` request формат (mock socket).
7. **`test_remote_api.py`** — Flask test client: status/control/auth.
8. **`test_source_manager.py`** — playlist manipulation, next/prev wrap-around,
   `set_radio_url`.
9. **`test_history.py`** — append, range query, CSV export.

### 7.4 Метрики качества

- **Coverage** ≥ 60% к концу Фазы 0, ≥ 80% к концу Фазы 1.
- **Ruff** — без E/F/W ошибок.
- **MyPy** (опционально) — strict только для `core/`.

---

## 8. CI / CD / Качество кода

### 8.1 GitHub Actions

`.github/workflows/ci.yml`:

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: sudo apt-get install -y libportaudio2 libsndfile1
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: pytest -q
```

### 8.2 `pyproject.toml`

PEP 621 metadata + `[tool.ruff]` + `[tool.pytest.ini_options]`.

### 8.3 Pre-commit (опционально)

`.pre-commit-config.yaml` с ruff + trailing-whitespace.

---

## 9. Definition of Done

Фича считается завершённой, когда:

1. ✅ Реализована в `core/` или `ui/` с docstrings.
2. ✅ Покрыта тестами (unit + integration где применимо).
3. ✅ `ruff check .` зелёный.
4. ✅ `pytest` зелёный.
5. ✅ Документирована в `README.md` И в этом roadmap (отмечена `[x]`).
6. ✅ Если меняет конфиг — миграция версий учтена.
7. ✅ Если расширяет Remote API — задокументирована в `docs/API.md`.
8. ✅ PR прошёл CI и code review.

---

## Приложение A — Краткая сводка приоритетов

```
P0 (Фаза 0)  Persistence (config.json)
P0 (Фаза 0)  M3U/PLS импорт+экспорт
P0 (Фаза 0)  ID3 теги в плейлисте
P0 (Фаза 0)  Кроссфейд (core логика + curves)
P0 (Фаза 0)  Remote API auth + расширения
P0 (Фаза 0)  Тесты + CI

P1 (Фаза 1)  Air Recorder
P1 (Фаза 1)  AutoDJ rules
P1 (Фаза 1)  10-band EQ + attack/release compressor
P1 (Фаза 1)  Day-of-week расписание
P1 (Фаза 1)  Hotkeys
P1 (Фаза 1)  CLI/headless

P2 (Фаза 2)  Spectrum analyzer
P2 (Фаза 2)  Multi-encoder streaming
P2 (Фаза 2)  Web UI v2
P2 (Фаза 2)  Multi-language
```

---

*Last updated: 2026-05-13*
