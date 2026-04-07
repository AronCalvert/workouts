desktop_file = i18n.merge_file(
  input: 'io.github.AronCalvert.Workouts.desktop.in',
  output: 'io.github.AronCalvert.Workouts.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

desktop_utils = find_program('desktop-file-validate', required: false)
if desktop_utils.found()
  test('Validate desktop file', desktop_utils, args: [desktop_file])
endif

install_data(
  'icons/hicolor/scalable/apps/io.github.AronCalvert.Workouts.svg',
  install_dir: get_option('datadir') / 'icons/hicolor/scalable/apps',
)

install_data(
  'icons/hicolor/symbolic/apps/io.github.AronCalvert.Workouts-symbolic.svg',
  install_dir: get_option('datadir') / 'icons/hicolor/symbolic/apps',
)

metainfo_file = i18n.merge_file(
  input: 'io.github.AronCalvert.Workouts.metainfo.xml.in',
  output: 'io.github.AronCalvert.Workouts.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
)

install_data(
  'screenshots/main-window.png',
  'screenshots/workout-detail.png',
  'screenshots/workout-run.png',
  'screenshots/rest-timer.png',
  'screenshots/workout-complete.png',
  'screenshots/history.png',
  install_dir: get_option('datadir') / 'metainfo/screenshots',
)

appstream_util = find_program('appstream-util', required: false)
if appstream_util.found()
  test('Validate metainfo file', appstream_util, args: ['validate', metainfo_file])
endif
