workouts_sources = files(
  '__init__.py',
  '__main__.py',
  'app.py',
  'db.py',
  'models.py',
  'prefs.py',
  'ui_utils.py',
  'window.py',
)

install_data(workouts_sources,
  install_dir: pkgdatadir / 'workouts',
)

subdir('pages')
subdir('widgets')
