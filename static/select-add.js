/* Widget "tendina con Aggiungi nuovo…" (macro select_add in _widgets.html).
   Scegliendo "➕ Aggiungi nuovo…" appare un campo: il valore digitato diventa
   un'opzione selezionata e viene inviato col form sotto il name della select. */
(function () {
  function aggiungiOpzione(inp) {
    var wrap = inp.closest('.select-add');
    if (!wrap) return;
    var sel = wrap.querySelector('.js-select-add');
    var v = (inp.value || '').trim();
    if (!v) { inp.classList.add('d-none'); sel.value = ''; return; }
    var opt = Array.prototype.find.call(sel.options, function (o) {
      return o.value.toLowerCase() === v.toLowerCase();
    });
    if (!opt) {
      opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      sel.insertBefore(opt, sel.querySelector('option[value="__add__"]'));
    }
    sel.value = opt.value;
    inp.value = '';
    inp.classList.add('d-none');
  }

  // Mostra/nascondi il campo quando si sceglie "Aggiungi nuovo…"
  document.addEventListener('change', function (e) {
    var sel = e.target;
    if (!sel.classList || !sel.classList.contains('js-select-add')) return;
    var wrap = sel.closest('.select-add');
    var inp = wrap && wrap.querySelector('.js-add-input');
    if (!inp) return;
    if (sel.value === '__add__') { inp.classList.remove('d-none'); inp.focus(); }
    else { inp.classList.add('d-none'); }
  });

  // Conferma il nuovo valore (Invio o uscita dal campo)
  document.addEventListener('keydown', function (e) {
    if (e.target.classList && e.target.classList.contains('js-add-input') && e.key === 'Enter') {
      e.preventDefault(); aggiungiOpzione(e.target);
    }
  });
  document.addEventListener('blur', function (e) {
    if (e.target.classList && e.target.classList.contains('js-add-input')) aggiungiOpzione(e.target);
  }, true);

  // Al submit finalizza eventuali campi "Aggiungi nuovo…" ancora aperti
  document.addEventListener('submit', function (e) {
    if (!e.target.querySelectorAll) return;
    e.target.querySelectorAll('.js-add-input').forEach(function (inp) {
      var sel = inp.closest('.select-add').querySelector('.js-select-add');
      if (sel.value === '__add__') aggiungiOpzione(inp);
    });
  }, true);

  // Checkbox con [data-toggle-target]: mostra/nasconde la sezione collegata
  function applicaToggle(cb) {
    var t = document.querySelector(cb.getAttribute('data-toggle-target'));
    if (t) t.classList.toggle('d-none', !cb.checked);
  }
  document.addEventListener('change', function (e) {
    if (e.target.matches && e.target.matches('[data-toggle-target]')) applicaToggle(e.target);
  });
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-toggle-target]').forEach(applicaToggle);
  });
})();
