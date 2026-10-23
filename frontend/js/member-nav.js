// ---------------------------------------------------------------------------
// member-nav.js - Menu dropdown and section switching for the member dashboard.
// Loaded after member.js. Pure UI; it does not touch the data or the API.
// ---------------------------------------------------------------------------

(function () {
  const menuBtn = document.getElementById("menu-btn");
  const menuList = document.getElementById("menu-list");
  const items = document.querySelectorAll(".menu-item");
  const views = document.querySelectorAll(".view");

  if (!menuBtn || !menuList) return;

  menuBtn.addEventListener("click", function (event) {
    event.stopPropagation();
    menuList.hidden = !menuList.hidden;
  });

  document.addEventListener("click", function () { menuList.hidden = true; });
  menuList.addEventListener("click", function (event) { event.stopPropagation(); });

  items.forEach(function (item) {
    item.addEventListener("click", function () {
      const target = item.dataset.view;
      items.forEach(function (i) { i.classList.toggle("active", i === item); });
      views.forEach(function (v) { v.classList.toggle("active", v.dataset.view === target); });
      menuList.hidden = true;
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
})();