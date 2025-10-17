document.addEventListener("DOMContentLoaded", async () => {
  const res = await fetch("/admin/chart-data");
  const data = await res.json();

  // Most Asked Categories
  if (data.categories && Object.keys(data.categories).length > 0) {
    new Chart(document.getElementById("categoryChart"), {
      type: "bar",
      data: {
        labels: Object.keys(data.categories),
        datasets: [{
          label: "Questions",
          data: Object.values(data.categories),
          backgroundColor: "#ffd000"
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } }
      }
    });
  }

  // Chat Volume by Hour
  if (data.hours && Object.keys(data.hours).length > 0) {
    new Chart(document.getElementById("hourChart"), {
      type: "bar",
      data: {
        labels: Object.keys(data.hours),
        datasets: [{
          label: "Chats",
          data: Object.values(data.hours),
          backgroundColor: "#90ee90"
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } }
      }
    });
  }

  // Top 10 Asked Questions
  if (data.questions && Object.keys(data.questions).length > 0) {
    new Chart(document.getElementById("topQuestionsChart"), {
      type: "bar",
      data: {
        labels: Object.keys(data.questions),
        datasets: [{
          label: "Times Asked",
          data: Object.values(data.questions),
          backgroundColor: "#87ceeb"
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { display: false } }
      }
    });
  }
});
