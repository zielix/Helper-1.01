# Asystent v0.1

Projekt jest podzielony na małe moduły, aby kolejne funkcje można było dodawać
bez mieszania obsługi procesu, skanowania i patchowania.

## Wymagania

| Co | Po co | Instalacja |
|---|---|---|
| Windows 10/11 | bot steruje oknem klienta przez WinAPI | — |
| Python 3.14 **x64** (obsługiwany jest też 3.13) | interpreter (OpenCV nie ma paczek dla ARM64) | `winget install -e --id Python.Python.3.14 --architecture x64` |
| `mss`, `numpy`, `opencv-python` | zrzuty ekranu i rozpoznawanie obrazu | `py -3.14 -m pip install -r requirements.txt` |
| Tesseract OCR | odczyt many (Health Info), nazw w Battle, tytułów okien | `winget install -e --id UB-Mannheim.TesseractOCR` |
| Klient RetronicDX (OTCv8) | gra | — |

Tesseract musi być w PATH albo w standardowym katalogu
(`C:\Program Files\Tesseract-OCR`). Bez niego nie działają Runemaker, Mana
trainer i rozpoznawanie Battle przez OCR; reszta działa.

Ustawienia ekranu: bot sprawdzano przy powiększeniu Windows 200%, ale sam
dopasowuje się do skali. Okno klienta musi być widoczne (nie zminimalizowane),
a w kliencie otwarte okna Battle i Health Info oraz główny plecak.

## Instalacja na nowym komputerze

```powershell
git clone <adres repozytorium>
cd <folder repozytorium>
winget install -e --id Python.Python.3.14 --architecture x64
winget install -e --id UB-Mannheim.TesseractOCR
py -3.14 -m pip install -r requirements.txt
```

Na Windows ARM (np. Parallels na Macu) Python x64 instaluje się obok
istniejącego i działa przez emulację.

## Uruchomienie

Uruchom klienta RetronicDX, a następnie:

```powershell
py -3.14 start_bot.py
```

Możesz też uruchomić `start_bot.bat` dwukrotnym kliknięciem. Okno bota ma
przycisk do włączania i wyłączania light hacka. Przy wyłączeniu i przy zamykaniu
interfejsu bot próbuje przywrócić oryginalne bajty klienta.

Panel zawiera też automat zaklęcia. Wpisz treść, ustaw zakres odstępu (obie
wartości minimum 1 sekunda) i włącz go. Bot losuje nowy odstęp przed każdą
kolejną próbą. Wysyłanie odbywa się tylko wtedy, gdy okno klienta jest aktywne;
po włączeniu wróć do gry. Każde zaklęcie jest wysyłane z klawiszem Enter.

Panel automatycznego jedzenia ma osobny zakres odstępu. Kliknij „Ustaw pozycję
jedzenia”, wróć do gry i kliknij prawym przyciskiem przedmiot. Ten klik użyje
jedzenia i zapisze jego pozycję względem okna klienta. Następnie włącz automat.
Klikanie jest wykonywane tylko wtedy, gdy klient jest aktywnym oknem.

Runemaker i Mana trainer są opisane niżej (karta „Runemaker”).

Odczyt many i automatyczne znajdowanie okna Battle wymagają zainstalowanego
Tesseract OCR (`winget install -e --id UB-Mannheim.TesseractOCR`) i dostępnego `tesseract.exe`
(w PATH albo w standardowym katalogu instalacji). Bez niego Runemaker i Mana trainer nie
uruchomią się; pozostałe funkcje nie wymagają Tesseract.

Wykrywanie Battle ma osobne ustawienia w kartach „Runemaker” i „Cavebot”. W każdej
karcie rozwiń „Kalibracja obszaru Battle”, ustaw lewy górny i prawy dolny róg
wierszy, zostaw pustą listę i włącz przełącznik „Wykrywanie Battle”. Profile nie mogą działać jednocześnie. Monitor zapisze
pusty obraz jako wzorzec, gdy klient będzie aktywny, i poczeka na powrót do gry,
jeśli przełączysz okno.

W zakładce „Runemaker” wykrycie wpisu Battle wstrzymuje Runemaker, uruchamia
sygnał dźwiękowy i wykonuje dwa kroki w lewo. Gdy lista pozostanie pusta,
wykonuje dwa kroki w prawo i wznawia Runemaker. Atak dozwolonych
potworów jest osobnym przełącznikiem karty „Cavebot”. OCR toleruje pojedyncze błędne
odczyty i nie klika ponownie celu tylko dlatego, że liczba wpisów chwilowo się
zmieniła.

Przełącznik ataku i listę wzorców znajdziesz w sekcji „Targeting” karty
„Cavebot”, a wysokość wiersza w „Edytorze celów”. Rozwiń go, wpisz nazwę potwora, zaznacz lewy górny i prawy dolny róg samej nazwy w Battle,
a bot zapisze wzorzec obrazu w folderze `battle_templates`. Powtórz dla każdego
dozwolonego potwora. Bot dopasowuje wzorce do poszczególnych wierszy i klika
rozpoznaną nazwę; dla nazw bez wzorca używa OCR. Jeśli wzorców nie zapisano,
działa dotychczasowe rozpoznawanie OCR. Status pokazuje, czy znaleziono wzorzec
lub nazwę i czy wysłano kliknięcie. OCR wymaga Tesseract.

Wykrywanie Battle wymaga pakietów `mss`, `opencv-python` i `numpy`. Zainstaluj
je poleceniem `py -3.14 -m pip install -r requirements.txt`.

Karta „Cavebot” łączy mapę, targeting i wykrywanie Battle (układ wzorowany na
XyroBocie: przełączniki On/Off, rzadziej używane ustawienia w zwijanych
sekcjach). Sekcja „Mapa” pokazuje pozycję postaci na mapie, bez czytania pamięci klienta. Nic nie trzeba ustawiać: bot sam
wczytuje najnowszą minimapę zapisaną przez klienta (`%APPDATA%\Retronic\…\*.otmm`,
a gdy jej brak — `maps/map74.otmm`), wczytuje ją ponownie, gdy klient zapisze
nowszą, i sam znajduje okno Minimap w oknie gry (wystarczy, że jest otwarte).
Potem co 0,3 s robi zrzut minimapy, zamienia go na siatkę kolorów pól i szuka
jej w pliku mapy. Skala i krzyżyk postaci wykrywają się same; gdy przesuniesz
okno minimapy, bot po kilku nieudanych odczytach znajdzie je ponownie. Kółko
myszy nad mapą zmienia przybliżenie, a pod mapą widać współrzędne pola pod
kursorem. Śledzenie można wyłączyć przełącznikiem „Śledzenie pozycji”; ustawienie i przybliżenie
zapisują się w `minimap_settings.json`. Na jednolitym terenie, np. pustyni lub
morzu, bot może zgłosić kilka pasujących miejsc i poczeka na charakterystyczny
fragment. Wymaga pakietów `mss`, `opencv-python` i `numpy`.

Sekcja „Trasa (waypointy)” to cavebot. Lewy klik w mapę bota dodaje waypoint
(za zaznaczonym na liście albo na końcu), prawy klik usuwa najbliższy,
przeciąganie przesuwa widok, a przyciski „Piętro ▲/▼” pokazują inne piętra.
„+ Pozycja postaci” dodaje pole, na którym stoisz. Waypoint „Idź” wystarczy
minąć o jedno pole, „Stój” wymaga wejścia dokładnie na pole — używaj go na
schodach i dziurach, bo po zmianie piętra bot przechodzi do kolejnego
waypointu na nowym piętrze. Po włączeniu przełącznika „Cavebot” bot zaczyna od
zaznaczonego waypointu (albo najbliższego na Twoim piętrze) i chodzi po trasie
w pętli: wyznacza drogę po polach z pliku `.otmm` i klika w minimapie klienta
najdalsze widoczne pole tej drogi, a klient sam prowadzi tam postać. Klika
ponownie dopiero, gdy postać dojdzie lub stanie; waypoint bez drogi albo bez
postępu przez 20 s jest pomijany. Opcja „Czekaj na koniec walki” przy
włączonym ataku zatrzymuje chodzenie, gdy postać bije cel albo w zasięgu jest
potwór z listy — potwory nieosiągalne nie zatrzymują trasy. Bez ataku cavebot
czeka, aż Battle się opróżni. Trasa,
lista potworów i opcje zapisują się w `cavebot.json`.

Każdy potwór na liście ma tryb walki „Goń” (Chase opponent, domyślnie) albo
„Stój” (Stand while fighting) — przycisk „Goń / Stój” zmienia go dla
zaznaczonego potwora. Przed atakiem (i co 2 s w trakcie) bot sprawdza przyciski
trybu walki w oknie Inventory klienta i klika właściwy, jeśli trzeba. Przyciski
znajduje sam na zrzucie klienta (wzorce `assets/combat_stand.png` i
`combat_chase.png`), a stan odczytuje po kolorze: wybrany tryb ma kolorową
ikonę, niewybrany szarą. Okno Inventory musi być otwarte.

Waypointy mają cztery typy: „Idź”, „Stój”, „Drabina” i „Lina”. Na waypoincie
„Drabina” bot staje dokładnie na polu i klika prawym przyciskiem w swoją postać
(Use), a na „Lina” — prawym w linę w plecaku (celownik „Use with…”) i lewym
w postać. Po zmianie piętra przechodzi do następnego waypointu na nowym
piętrze; gdy piętro się nie zmieni, ponawia akcję co 4 s, najwyżej 3 razy.
Przed pierwszym użyciem rozwiń „Lina i drabina — ustawienia” i zaznacz
Shift + lewym klikiem środek swojej postaci i linę w plecaku. Wymaga to
klasycznego sterowania w kliencie (prawy klik = Use). Na mapie bota takie
waypointy są rombami.

Sekcja „Targeting” zawiera listę atakowanych potworów: wpisz nazwę, kliknij
„Dodaj potwora”, a zbędne usuń przyciskiem „Usuń zaznaczonego”. Przy każdej
nazwie widać, czy bot rozpozna ją obrazem (zapisany wzorzec), czy przez OCR.

Okno bota dopasowuje się do powiększenia ekranu Windows (np. 200%), więc jest
ostre i nie zmienia nagle rozmiaru.

Wszystkie karty mają ten sam układ: kolumny, każda sekcja w wyraźnej ramce
z tytułem, w każdym module przełącznik On/Off w wierszu z nazwą, pod nim linia stanu, ustawienia w ramce, a dłuższe
wyjaśnienia pod znaczkiem ⓘ (najedź myszą). Karta „Panel” ma opcję „Okno bota
zawsze na wierzchu”. W pasku stanu działające moduły świecą na zielono.

Na dole okna, na każdej karcie, jest pasek stanu: pozycja postaci, stan
cavebota (aktualny waypoint), targetingu, atakowany cel z przybliżonym HP i tryb
(Human/zwykły). Obok jest czerwony przycisk „STOP wszystko”, a pod paskiem
mini-log ostatnich zdarzeń (atak, przełączenie celu, waypointy, profile). Klawisz
F12 działa jak STOP także wtedy, gdy aktywne jest okno gry: zatrzymuje atak,
cavebota, wykrywanie Battle, zaklęcia, jedzenie, zbieranie amunicji i runy
(light hack zostaje bez zmian). Uwaga: jeśli masz w kliencie coś pod F12,
klient też to wykona.

Profile (wiersz „Profil” w karcie „Cavebot”) zapisują trasę, listę potworów,
ignorowane potwory i opcje pod nazwą w folderze `profiles/`. „Zapisz jako…”
tworzy lub nadpisuje profil, „Wczytaj” podmienia bieżącą trasę i potwory
(zatrzymuje cavebota i atak), „Usuń” kasuje plik profilu. Bieżący stan nadal
zapisuje się na bieżąco w `cavebot.json`.

Kolejność na liście atakowanych potworów to priorytet: bot atakuje najpierw
potwora wyżej na liście (▲/▼ zmienia kolejność), a przy kilku takich samych —
tego wyżej w Battle. „Ignoruj / przywróć” wyłącza potwora z ataku bez usuwania
go z listy i wzorca.

Karta „Cavebot” ma trzy kolumny i mieści się bez przewijania: po lewej chodzenie
(przełącznik, stan, waypointy), w środku mapa (dopasowuje się do szerokości
kolumny), po prawej targeting (przełącznik ataku, lista atakowanych potworów,
okno Battle). Profil i tryb Human są w jednej linii nagłówka. Śledzenie pozycji z minimapy działa zawsze, bez przełącznika.

Okno Battle bot znajduje sam: po włączeniu ataku albo cavebota (lub przyciskiem
„Znajdź okno Battle teraz”) czeka, aż wrócisz do gry, robi zrzut całego klienta,
znajduje nagłówki małych okien po przycisku zamykania (wzorzec
`retronic_bot/assets/window_close.png`, w każdej skali), odczytuje ich tytuły
przez Tesseract OCR i wybiera okno „Battle”; dół okna wyznacza listwa zmiany
rozmiaru. Wystarczy, że okno Battle jest otwarte (Ctrl+B w kliencie).
Wykrywanie wpisów Battle włącza się samo razem z atakiem lub z cavebotem
(gdy zaznaczone jest „Czekaj na koniec walki”). Ręczne
zaznaczenie obszaru zostało jako awaryjna opcja „Ręczny obszar Battle”.

Potwory do atakowania najwygodniej dodać przyciskiem „+ Dodaj z Battle”:
kliknij go, wróć do gry i kliknij potwora w oknie Battle. Bot w chwili
wciśnięcia przycisku robi zrzut Battle, wycina nazwę z klikniętego wiersza
(tekst tuż nad paskiem życia, w jego szerokości, więc obrazek postaci i jego
biała ramka podświetlenia pod kursorem nie trafiają do wzorca), zapisuje ją jako wzorzec w
`battle_templates`, odczytuje nazwę przez OCR i dodaje potwora do listy; pod
przyciskiem widać wycięty wzorzec. Jeśli OCR źle odczyta nazwę, wpisz ją w
pole i powtórz. Pole „Dodaj nazwę” dodaje potwora bez wzorca (rozpoznawanie
samym OCR, mniej pewne).

Targeting działa w trzech stanach: brak celu → kliknięto → cel potwierdzony.
Co ok. 0,75 s bot robi jeden zrzut Battle i odczytuje z niego każdy wiersz:
nazwę (wzorzec lub OCR), % HP z paska życia i czerwoną ramkę atakowanego celu.
Dopóki cel ma ramkę, bot nic nie klika (ponowne kliknięcie wyłączyłoby atak);
koniec ataku uznaje dopiero po dwóch odczytach bez ramki. Po kliknięciu czeka
na ramkę z rosnącą przerwą (2 s, 3 s, 4,5 s, 6,75 s); po 4 nieudanych próbach
robi 6 s przerwy.

Bot patrzy też na samą mapę gry. Znajduje ją raz (prostokąt 15 × 11 pól
z czarną ramką), a potem odczytuje paski życia nad stworami i przelicza je na
pola względem postaci — własny pasek poznaje po niebieskim pasku many pod
spodem. Z pozycji z minimapy i mapy `.otmm` liczy drogę do każdego potwora,
traktując pola innych stworów jako zajęte, więc od razu wie, że szczura w
tunelu zasłaniają dwa inne.

Wybór celu: najpierw priorytet z listy, potem najbliższy osiągalny, potem
najmniej HP (dobijanie uciekających). Gdy w Battle są wyłącznie potwory
z listy jednego rodzaju, a liczba stworów na mapie zgadza się z Battle, bot
atakuje prawym klikiem prosto na mapie wybranego (najbliższego) potwora; w
innym wypadku klika wiersz Battle, żeby nigdy nie trafić w gracza ani NPC.
Prawy klik na mapie wymaga klasycznego sterowania — jeśli dwa razy nie
zadziała, bot wraca do klikania w Battle. Potwory nieosiągalne są pomijane.

W trakcie ataku bot zmienia cel tylko wtedy, gdy atakowany potwór jest
nieosiągalny przez 1,5 s (czerwony kwadrat na mapie pokazuje, który to) albo
jego pasek nie maleje przez 7 s. Pojawienie się potwora z wyższym priorytetem
nie przerywa walki — bot dobija bieżący cel, a priorytet decyduje o kolejnym. Gdy bot nie widzi mapy gry albo pozycji z
minimapy, działa jak dawniej, z samą listą Battle i regułą 7 s.

Przełącznik „Tryb Human” (w nagłówku karty „Cavebot”, dotyczy wszystkich
funkcji) sprawia, że bot nie działa jak automat. Ruch myszy nie jest skokiem
ani idealnie gładką krzywą: to niedokładny rzut w okolice celu i jedna–dwie
poprawki, z drżeniem, nierównym tempem, czasem z przestrzeleniem lub
zawahaniem; czas ruchu rośnie z odległością. Przycisk jest wciśnięty losowy
czas, a kursor nie wraca w ułamku sekundy na poprzednie miejsce. Atak reaguje
z nieregularnym opóźnieniem (zwykle 0,3–0,7 s, czasem dłużej) i klika w losowy
punkt nazwy. Cavebot klika w losowe miejsce pola i nie zawsze w najdalszy punkt
trasy, odczekuje chwilę po dojściu do waypointu i co kilka minut robi krótką
przerwę. Ustawienie zapisuje się w `cavebot.json`.

Karta „Trainer” zbiera kamienie lub spiry z ziemi i przeciąga je do lewej
ręki — przy treningu w miejscu i przy chodzeniu za potworami (np. goblinami).
Z włączonym „Pola wokół postaci” (3 × 3 albo 5 × 5) bot sam znajduje mapę gry
i bierze pola wokół postaci, więc obszar idzie razem z nią; ręczne rogi obszaru
zostały w zwijanej sekcji. Slot lewej ręki zaznaczasz raz klawiszem Shift +
lewy klik (zapisuje się w `automation.json`). Wzorce przedmiotów: połóż
przedmiot na ziemi, wpisz nazwę i zaznacz rogi samego przedmiotu; wzorzec
trafi do folderu `pickup_templates`. Stos kilku kamieni wygląda inaczej niż
jeden — zapisz wzorzec dla każdego wyglądu. Bot przeciąga najlepiej
dopasowany przedmiot do ręki (z Ctrl, aby przenieść cały stos) i pomija na
30 s miejsce, którego nie udało się podnieść w trzech próbach.

Sekcja „Wędkowanie” w karcie „Trainer” łowi ryby: prawy klik na wędce
(celownik „Use with…”), potem lewy klik w losowe pole wody w zasięgu (1–7 pól,
domyślnie 6), z losowym odstępem i bez powtarzania ostatnich pól. Wodę bot
zna z pliku `.otmm` (kolor 40 na minimapie) i pozycji z minimapy. Brzeg ma na
minimapie kolor wody, ale łowić na nim się nie da, więc bot rzuca tylko w pola
otoczone wodą ze wszystkich 8 stron. Na zrzucie
mapy gry sprawdza, czy pole jest niebieskie — pomija pola zasłonięte np. przez
statek. Bez pozycji z minimapy szuka wody tylko po kolorze na zrzucie.
Złowione ryby klient kładzie w osobnych slotach plecaka, więc co kilka rzutów
(domyślnie 3) bot przeciąga rybę z pierwszego slotu na kolejny stos (zwykłe
przeciągnięcie, bez Ctrl), aż zostanie jeden. Gdy przeciągnięcie nic nie zmieni, uznaje stos
docelowy za pełny (100 sztuk) i łączy z następnym. Raz zaznacz Shift + lewym
klikiem wędkę i jedną rybę w plecaku (wzorzec ryby, potrzebny tylko do
łączenia). Wędka nie musi być w plecaku — najlepiej trzymać ją w ręce albo
w innym pojemniku niż ryby: nowa ryba wchodzi na pierwszy slot i przesuwa
pozostałe przedmioty plecaka, więc wędka w tym samym plecaku zmieniałaby
miejsce. Wymaga klasycznego sterowania (prawy klik = Use); ustawienia
zapisują się w `automation.json`, wzorzec ryby w `item_templates/fish.png`.

### Ciała i loot (karta „Loot”)

Wszystko, co dotyczy ciał, jest w osobnej karcie „Loot”; w karcie „Cavebot”
zostaje tylko linia z bieżącym ustawieniem. Opcje zapisują się w profilu
cavebota (`cavebot.json` i profile w `profiles/`), a slot plecaka — jak pozycje
liny i postaci — tylko w `cavebot.json`.

Ciała otwiera targeting (włączony „Atak potworów z listy”), z cavebotem albo
bez niego (opcja „Otwieraj ciała po walce”). Działa to tak:

- **Zabicie.** Gdy znika czerwona ramka celu, bot uznaje go za zabitego, jeśli
  na mapie gry jego ostatnie pole jest puste (słabe potwory giną między
  odczytami, więc HP w ostatnim odczycie bywa 100%). Bez mapy gry: cel
  zniknął z Battle albo miał najwyżej 60% HP. Gdy bot nie zna pola celu
  (nie widział czerwonego kwadratu), zapisuje w logu „Zabity: …, ale nie
  znam pola ciała”.
- **Od razu albo po walce.** Domyślnie („Otwieraj ciało od razu po zabiciu”)
  bot otwiera ciało zabitego potwora, zanim zaatakuje następnego — inne
  potwory mogą go w tym czasie bić. Po wyłączeniu tej opcji pole zabitego
  celu (w koordynatach świata z minimapy) trafia do kolejki, a bot walczy
  dalej z resztą potworów. Gdy nie ma już kogo atakować, otwiera ciała od
  najbliższego; cavebot w tym czasie stoi.
  Ciała starsze niż 60 s, z innego piętra albo spoza widoku gry pomija.
  Bez pozycji z minimapy ciało otwiera od razu po zabiciu.
- **Okno ciała.** Przed kliknięciem bot zamyka okna starych ciał (nowe ciało
  otworzyłoby się w tym samym oknie). Po prawym kliku w pole ciała klient
  sam podchodzi do dalszego ciała, a bot czeka na zmianę okien: co najmniej
  2 s (plus 0,6 s za każde pole odległości), dłużej — dopóki postać idzie
  (pozycja z minimapy się zmienia), najwyżej 10 s; i
  rozpoznaje ciało po tytule okna („Dead…”, „Slain…”, „Remains…”, Tesseract
  OCR) — otwarcie ciała przestawia inne okna panelu, więc same pozycje okien
  nie wystarczają. Bez Tesseract bierze najmniejsze nowe okno. Po
  wszystkim zamyka okno ciała. Żeby było szybko: okna szuka tylko
  w panelach obok mapy gry i w skali zapamiętanej z poprzedniego ciała
  (ok. 0,2 s zamiast kilku sekund na całym kliencie), a odczytane tytuły
  pamięta (Tesseract to ok. 1,5 s na tytuł; nowe czyta równolegle).
  Pierwsze ciało w sesji trwa kilka sekund, kolejne ok. 1–2 s.
- **Meat.** Bot najeżdża kursorem na mięso, chwilę czeka (klient musi
  zauważyć kursor nad przedmiotem) i klika prawym przyciskiem, a potem
  sprawdza na zrzucie, czy slot się zmienił (zniknęło albo zmalała liczba
  sztuk). Jeśli nie, po sekundzie próbuje jeszcze raz — serwer odrzuca
  użycie przedmiotu tuż po otwarciu ciała. Obraz `…_meat.png` w `loot_debug/`
  pokazuje miejsce kliknięcia (czerwony krzyżyk) i slot po ostatniej próbie.
- **Log.** Wynik każdego ciała trafia do `battle_attack.log` jako wiersz
  `Loot: …` z czasami etapów (stare ciała, okno, tytuły, sloty, meat, loot).
  Przedmioty rozpoznane, ale bez „Zabieraj”, są wypisane jako „Pomijam (bez
  »Zabieraj«)”.
- **Sloty.** Wyznacza je sam z obrazu (okres i położenie ramek slotów,
  w każdej skali klienta, z pominięciem paska przewijania) i porównuje ikony
  z wzorcami z folderu `loot_patterns` (manifest `patterns.json`).

Lootowanie — krok po kroku:

1. Włącz „Zapisuj wzorce nowych przedmiotów” i zabij kilka potworów.
   Nieznane ikony trafiają do katalogu jako „Nowy przedmiot 00NN” i są
   **domyślnie pomijane**.
2. W sekcji „Katalog przedmiotów” nadaj wzorcom nazwy i zaznacz „Zabieraj
   (loot)” przy tych, które bot ma brać; zbędne usuń przyciskiem „Usuń
   wzorzec”. Ikonę mięsa nazwij dokładnie `Meat` — przy opcji „Jedz »Meat«
   z ciał” bot je zje (niezależnie od „Zabieraj”, które dotyczy tylko
   przenoszenia do plecaka).
3. Otwórz plecak na loot, kliknij „Ustaw slot plecaka” i Shift + lewym
   klikiem wskaż w nim pusty slot.
4. Włącz przełącznik „Zabieraj loot do plecaka”.

Po walce bot przeciąga zaznaczone przedmioty z ciała na ten slot (klient
przenosi cały stos zwykłym przeciągnięciem), po każdym przeciągnięciu
sprawdza na zrzucie, czy przedmiot zniknął z ciała, a na koniec zamyka okno
ciała. Gdy przedmiot dwa razy z rzędu zostaje w ciele (pełny plecak, za mały
udźwig), bot przestaje i pisze o tym. Bot nie lootuje, gdy zaznaczony slot nie
leży w żadnym otwartym oknie albo zasłoniło go okno ciała. STOP / F12
przerywa lootowanie między przeciągnięciami.

Sekcja „Ostatnie ciało” pokazuje obraz okna ostatniego ciała z wykrytymi
slotami (szare: pusty slot, zielone: rozpoznany wzorzec, żółte: nieznany
przedmiot), historię ostatnich ciał i to, co zabrano w tej sesji. Te same
obrazy (ostatnie 20) są w folderze `loot_debug/` — przycisk „Otwórz folder
loot_debug”. Jeśli loot nie działa, zacznij od nich.

Diagnostyka ataku trafia do `battle_attack.log`. Gdy plik przekroczy ok. 1 MB,
bot przenosi go do `battle_attack.log.1` i zaczyna nowy, więc na dysku są
najwyżej dwa takie pliki.

Karta „Runemaker” ma dwa moduły; manę oba biorą z okna Health Info klienta,
które bot znajduje sam (OCR napisu „aktualna / maksymalna”, a między odczytami
długość niebieskiego paska):

- **Runemaker** — gdy mana przekroczy próg (%): przedmiot z prawej ręki idzie
  do głównego plecaka (slot plecaka w Inventory), blank runa z otwartego
  plecaka do prawej ręki, bot rzuca zaklęcie, gotową runę odkłada w miejsce,
  z którego wziął blank, i wkłada przedmiot z powrotem do ręki. Każdy krok
  sprawdza na zrzucie i w razie potrzeby ponawia; gdy nie znajdzie przedmiotu
  z ręki albo nie może odłożyć runy, zatrzymuje się z alarmem. Bez blanków nie
  rusza ręki i sprawdza znowu co 30 s. Raz zaznacz Shift + lewym klikiem slot
  prawej ręki, slot plecaka w Inventory i blank runę (wzorzec). Główny plecak
  musi być otwarty.
- **Mana trainer** — rzuca zaklęcie (np. `utevo lux`), gdy mana przekroczy
  próg, w losowych odstępach. Gdy Runemaker jest włączony i ma blanki, trener
  czeka, żeby mana szła na runy.

Ustawienia obu kart zapisują się w `automation.json`.

Jedyną funkcją, która sięga do pamięci klienta, jest light hack. Zmiana dotyczy
wyłącznie uruchomionego procesu i znika po jego zamknięciu; skrypt nie zapisuje
zmian w pliku EXE. Pozostałe funkcje działają na zrzutach ekranu i symulowanej
klawiaturze/myszy, a uchwyt procesu otwierają tylko z prawem sprawdzenia, czy
klient działa (bez odczytu i zapisu pamięci).

## Struktura

- `retronic_bot/config.py` — stałe i sygnatura klienta.
- `retronic_bot/process.py` — wyszukiwanie procesu i modułu.
- `retronic_bot/memory.py` — odczyt, zapis i uprawnienia pamięci procesu.
- `retronic_bot/pe.py` — odczyt położenia sekcji `.text` z PE.
- `retronic_bot/scanner.py` — skanowanie sekcji pamięci po sygnaturze.
- `retronic_bot/patcher.py` — budowanie i aplikowanie patcha.
- `retronic_bot/controller.py` — stan przełącznika i przywracanie oryginalnego kodu.
- `retronic_bot/gui.py` — graficzny panel sterowania.
- `retronic_bot/creatures.py` — mapa gry: stwory, cel ataku, osiągalność.
- `retronic_bot/runemaker.py` — mana z Health Info, wzorce i wyszukiwanie przedmiotów.
- `retronic_bot/keyboard.py` — bezpieczne wysyłanie tekstu i naciśnięć klawiszy do aktywnego klienta.
- `retronic_bot/mouse.py` — przechwycenie pozycji oraz kliknięcia/przeciąganie.
- `retronic_bot/battle.py` — przechwycenie, porównanie i OCR listy Battle.
- `retronic_bot/pickup.py` — wzorce i wyszukiwanie amunicji na ziemi.
- `retronic_bot/fishing.py` — pola wody w widoku gry i łączenie stosów ryb w plecaku (bez GUI).
- `retronic_bot/cavebot.py` — waypointy, wyznaczanie drogi i chodzenie przez minimapę.
- `.claude/skills/asystent-ui/` — skill z zasadami UI bota i skryptem zrzutów kart
  (`shot_tabs.py`); spakowany jako `asystent-ui.skill`.
- `retronic_bot/human.py` — tryb Human: ruchy myszy i opóźnienia jak u człowieka.
- `retronic_bot/battle_window.py` — automatyczne znalezienie okna Battle na zrzucie klienta.
- `retronic_bot/minimap.py` — wyszukanie pliku `.otmm` i minimapy w oknie gry oraz pozycja postaci.
- `maps/` — pliki minimapy `.otmm`.
- `retronic_bot/mana.py` — odczyt wartości many przez Tesseract OCR.
- `retronic_bot/combat_mode.py` — wykrywanie i przełączanie trybu walki (Goń / Stój) w Inventory.
- `retronic_bot/targeting.py` — kolejność celów, śledzenie HP celu i progi zmiany celu (bez GUI).
- `retronic_bot/corpse.py` — otwieranie ciała ostatniego celu i rozpoznawanie przedmiotów (bez GUI).
- `retronic_bot/loot_patterns.py` — katalog wzorców przedmiotów z ciał (`loot_patterns/`).
- `loot_patterns/`, `battle_templates/` — zapisane wzorce obrazów (manifesty JSON + PNG).
- `tests/` — testy jednostkowe czystej logiki (`py -3.14 -m unittest discover -s tests -t .`).
- `retronic_bot/__main__.py` i `start_bot.py` — punkty startowe programu.
- `start_bot.bat` — launcher dla Windows.

