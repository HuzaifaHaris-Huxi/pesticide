module.exports = {
  content: [
    '../templates/**/*.html',
    '../../templates/**/*.html',
    '../../**/*.py',
  ],
  safelist: [
    'bg-indigo-700', 'bg-emerald-700', 'bg-rose-700', 'bg-amber-700',
    'border-indigo-700', 'border-emerald-700', 'border-rose-700', 'border-amber-700',
    'text-indigo-700', 'text-emerald-700', 'text-rose-700', 'text-amber-700',
    'hover:bg-indigo-100', 'hover:bg-emerald-100', 'hover:bg-rose-100', 'hover:bg-amber-100',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
