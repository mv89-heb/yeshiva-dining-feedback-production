document.addEventListener("DOMContentLoaded", function () {
  const printButton = document.getElementById("print-flyer");
  if (!printButton) return;
  printButton.addEventListener("click", function () {
    window.print();
  });
});
