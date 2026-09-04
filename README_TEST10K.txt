AIDAR TENDERS / PROCUREVISION KZ
TEST10K MULTIPAGE STABLE - КОНТРОЛЬНАЯ ТОЧКА
Дата: 04.09.2026

1. СМЫСЛ TEST10K
TEST10K проверяет не один лот и не одну страницу Samruk, а многостраничную выдачу.
Контрольный запрос: картридж.
Статус: Опубликовано.
Samruk показал 24 лота, то есть 10 + 10 + 4 на нескольких страницах.

2. ЧТО ДОКАЗАНО
- TEST10K видит все 24 лота текущей выдачи Samruk.
- Запись 24 строк в Supabase прошла успешно.
- Supabase вернула HTTP 200.
- Ошибок обработки не было.
- После обновления все 24 лота находятся в базе.
- После обновления все 24 лота имеют техспецификацию.
- Новый лот 4527120 найден в портале ProcureVision KZ.
- В карточке 4527120 отображается блок "Техспецификация - данные из Supabase".

3. КОНТРОЛЬНАЯ ДИАГНОСТИКА ДО ОБНОВЛЕНИЯ
/diagnose-techspecs:
current_rows: 24
with_techspec: 16
without_techspec: 8
not_in_db: 8
available_for_batch: true
safe_mode: true
writes_supabase: false
downloads_pdf: false

4. ОБНОВЛЕНИЕ SUPABASE
/update-samruk:
ok: true
rows: 24
http: 200
pending_errors: 0
auto_techspec_downloaded: 3
auto_techspec_errors: 0

Автоматически скачаны и сохранены техспецификации:
- 4527120
- 4527121
- 4527122

5. КОНТРОЛЬНАЯ ДИАГНОСТИКА ПОСЛЕ ОБНОВЛЕНИЯ
/diagnose-techspecs:
current_rows: 24
with_techspec: 24
without_techspec: 0
not_in_db: 0

6. ПРОВЕРКА В ПОРТАЛЕ
До TEST10K в портале было 4 904 записи.
После TEST10K стало 4 912 записей.
Прирост: 8 новых лотов.

Контрольный лот:
4527120
Предмет: Услуги по заправке картриджей
Источник: Samruk
Сумма: 14 400 тг
Срок: 08.09.2026 22:24

Карточка 4527120 содержит техспецификацию из Supabase:
- закупка: 1252034
- лот: 4527120
- место поставки: Жамбылская область, Шу
- оплата: окончательный платеж 100%
- назначение: заправка копировально-множительной техники и оргтехники, PANTUM M7100
- технические требования отображаются в карточке.

7. РАБОЧИЕ ФАЙЛЫ TEST10K
- procurevision_bridge_TEST10K_MULTIPAGE.py
- RUN_BRIDGE_TEST10K_MULTIPAGE.bat

Вспомогательные файлы, которые остаются необходимыми:
- START_SAMRUK_CHROME.bat
- extract_samruk_techspec.py
- index.html

8. НЕ ЗАГРУЖАТЬ В ПУБЛИЧНЫЙ GITHUB
- config.txt
- samruk_chrome_profile/
- Supabase service_role key
- пароли
- ЭЦП
- токены авторизации

9. РЕКОМЕНДУЕМЫЙ GITHUB COMMIT
TEST10K Stable - multipage Samruk check

10. РЕКОМЕНДУЕМАЯ СТАБИЛЬНАЯ ВЕТКА
test10k-stable

11. ТОЧКА ПРОДОЛЖЕНИЯ
TEST10K можно считать стабильной контрольной точкой Samruk.
Следующие работы лучше вести уже после фиксации:
- загрузить TEST10K файлы, README, PDF и PowerPoint в GitHub;
- создать ветку test10k-stable;
- затем делать следующий этап отдельно: журнал ошибок, один понятный запуск, эксплуатационная упаковка Samruk.
