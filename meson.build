project('workouts',
  version: '0.1.0',
  meson_version: '>= 0.62.0',
  license: 'GPL-3.0-or-later',
)

i18n = import('i18n')
gnome = import('gnome')
python = import('python').find_installation('python3')

pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()

conf = configuration_data()
conf.set('PYTHON', python.full_path())
conf.set('VERSION', meson.project_version())
conf.set('pkgdatadir', pkgdatadir)

subdir('po')
subdir('data')
subdir('bin')
subdir('workouts')

gnome.post_install(
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
