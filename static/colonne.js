// Selettore colonne per le liste (Clienti / Pratiche).
// Salva la scelta in un cookie cols_<nome> e ricarica la pagina.
function applicaColonne(nome) {
  var box = document.getElementById('colonne-' + nome);
  if (!box) return;
  var keys = Array.prototype.slice
    .call(box.querySelectorAll('input[type=checkbox]:checked'))
    .map(function (i) { return i.value; });
  var val = keys.length ? keys.join(',') : 'none';
  document.cookie = 'cols_' + nome + '=' + val + ';path=/;max-age=31536000;samesite=lax';
  location.reload();
}
