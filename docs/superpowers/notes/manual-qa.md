# Manual QA checklist

These checks need a person at an unlocked screen. During development the display was locked, so automated checks covered only logic, the panels in isolation and the screenshot CLI. Each line is: action, then the expected result.

Setup: run from the repository root with the virtual environment. To keep your real plant, use a scratch state file, for example `python -m fernal --state %TEMP%\fernal-qa.json --theme normal --seed 3` (delete that file to repeat the first-run checks). Items 20 and 21 edit a state file by hand; quit the program first.

1. [ ] First launch (no state file): the window opens near the top-left of the primary screen, 420 x 640, with transparent corners and no taskbar button; a young leafy tree in a celadon pot, a sun disc in the top band, a tray icon appears.
2. [ ] Left-drag the plant: the window follows the cursor without lag and stays where released; a click without moving does not move it.
3. [ ] Shift + left-drag: the camera orbits (horizontal drag turns, vertical drag tilts, tilt stops at -10 and 60 degrees) and the window itself does not move.
4. [ ] Mouse wheel over the plant: zooms smoothly in and out and stops at the nearest and farthest distance without jumping.
5. [ ] Right-click the plant: a menu opens at the cursor with 물 주기, 영양제, 온도 조절, 스프레이, 설정, 테마, 화분 바꾸기…, 클릭 통과, 종료; a click outside closes it without doing anything.
6. [ ] Each menu entry: 물 주기, 영양제, 온도 조절, 스프레이 and 설정 each open their panel beside the window; 테마 shows three checkable entries with the current one ticked and switching one changes the look at once and moves the tick; 화분 바꾸기… opens a file dialog filtered to .glb and .gltf; 종료 quits and removes the tray icon.
7. [ ] Tray icon: left-click pops up the menu at the cursor, right-click shows the same menu, a click elsewhere closes it, the tooltip reads "Fernal".
8. [ ] Click-through on (tick 클릭 통과): clicks and the wheel go to the window behind the plant, the plant stays visible on top and does not react (no menu, no hover effect).
9. [ ] Click-through off: with it on, left-click the tray icon and untick 클릭 통과; the plant takes clicks again. Quit and relaunch: it starts off.
10. [ ] Water panel: it fades in over about 150 ms to the right of the window (to the left if there is no room); drag it by the title, Esc closes it; press 물 주기 and the button reads "물을 줬어요" for about 1.6 s, the needle rises by about 20 points and the sentence above the gauge updates.
11. [ ] Nutrients and spray panels: same behavior; the needle rises about 30 and 15 points, the button confirms with "영양제를 줬어요" and "스프레이를 뿌렸어요"; opening several panels cascades them down and outward instead of stacking exactly.
12. [ ] Climate slider: drag it between -10 and +10 for 5 seconds; the panel stays smooth, the reading says "난방으로 N°C 올리는 중" or "냉방으로 N°C 내리는 중" (at 0 "냉난방이 꺼져 있어요"), "현재 …°C" moves by the same amount, and the branches visibly bend within about a second after you pause.
13. [ ] Settings, city (needs network): type 부산 and press 찾기 or Enter; the status shows "찾는 중…" then "위치: …", and the sun moves; an unknown name or no network shows "도시를 찾지 못했습니다" and changes nothing.
14. [ ] Settings, theme: clicking 세계수, 일반 나무, 열매 나무 switches glow, motes and fruit at once, recolors the accent of every open panel, and the right-click menu tick follows.
15. [ ] Settings, pot: choose a valid .glb and the pot is replaced, about 54 cm wide with its rim at the soil line; choose a text file renamed to .glb and the default pot stays visible (no empty space); 기본 화분 restores the default and the file name line reads "기본 화분 사용 중".
16. [ ] Settings, window size: enter 300 x 500 and press 적용; the window resizes, the button reads "적용됨", the plant stays framed; quit and relaunch keeps the size.
17. [ ] Debug panel: click the plant, press Ctrl+Shift+D; the panel opens beside the window. It also opens with Ctrl+Shift+D from any other open panel, and Ctrl+Shift+right-click on the plant opens it without the menu appearing.
18. [ ] Debug controls: time scale at ×1000 grows the plant visibly within seconds; the growth slider from 0 to 100 regrows it smoothly; pinning water at 0 browns and droops the leaves; 시드 재추첨 gives a different shape; 초기화 returns to a young tree at ×8. The live readout of 애정도 rises about 5 points per hover or click on the plant. Set the time scale back afterwards.
19. [ ] Quit and relaunch: move the window, switch the theme, quit from the menu, start again; position, theme and plant continue (no new plant) and the pot is unchanged.
20. [ ] Off-screen recovery: quit, set `window.x` in the state file to 99999 (and once with the saved screen unplugged if you have two monitors), relaunch; the window opens centered on the primary screen. With `pot_path` set to a file that does not exist the default pot shows and nothing complains.
21. [ ] Catch-up after a long absence: quit, set `last_saved` in the state file to 3 days ago (then 30 days ago), relaunch; no dialog or message appears and the window opens within about a second, the plant is older and its water and nutrients lower; 30 days gives the same result as 7.
22. [ ] High DPI: at 150 percent and 200 percent scaling, and when dragging the window to a monitor with a different scale, the window, panels, text, sun glow and tray icon are sharp, correctly sized and not clipped.
23. [ ] No console and clean exit: start with `.venv\Scripts\pythonw -m fernal`; no console window opens; quit from the tray right after startup; the pythonw process is gone from Task Manager within about 6 seconds.
