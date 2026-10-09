document.addEventListener("click", (event) => {
  const message = event.target.closest(".flash");
  if (message) {
    message.remove();
  }
});
