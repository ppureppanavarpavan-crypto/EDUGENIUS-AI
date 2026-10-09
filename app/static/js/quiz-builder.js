const questionList = document.querySelector("#question-list");
const addQuestionButton = document.querySelector("#add-question");

if (questionList && addQuestionButton) {
  addQuestionButton.addEventListener("click", () => {
    const currentCount = questionList.querySelectorAll(".question-editor").length;
    if (currentCount >= 10) return;

    const first = questionList.querySelector(".question-editor");
    const clone = first.cloneNode(true);
    clone.querySelector(".question-number").textContent = String(currentCount + 1);
    clone.querySelectorAll("input, textarea").forEach((field) => {
      field.value = "";
    });
    clone.querySelector("select").selectedIndex = 0;
    const removeButton = document.createElement("button");
    removeButton.className = "button button-outline button-small remove-question";
    removeButton.type = "button";
    removeButton.textContent = "Remove question";
    removeButton.addEventListener("click", () => {
      clone.remove();
      questionList.querySelectorAll(".question-number").forEach((number, index) => {
        number.textContent = String(index + 1);
      });
    });
    clone.append(removeButton);
    questionList.append(clone);
  });
}
