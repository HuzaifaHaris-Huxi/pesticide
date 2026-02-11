      // Toast functionality (unchanged)
      (function () {
        const backDrop = document.getElementById("toast-backdrop");
        function removeToast(el) {
          el.style.transition = "opacity .25s ease, transform .25s ease";
          el.style.opacity = "0";
          el.style.transform = "translateY(6px) scale(0.98)";
          setTimeout(() => {
            el.remove();
            if (!document.querySelector("[data-toast]")) {
              backDrop && backDrop.remove();
            }
          }, 260);
        }

        document.querySelectorAll("[data-toast]").forEach((el) => {
          setTimeout(() => removeToast(el), 3000);
        });

        document.addEventListener("click", (e) => {
          const okBtn = e.target.closest("[data-action='toast-ok']");
          if (okBtn) {
            const toast = okBtn.closest("[data-toast]");
            if (toast) removeToast(toast);
          }
        });
      })();

      // Combined initialization
      document.addEventListener("DOMContentLoaded", function () {
        // Initialize sidebar
        new FuturisticSidebar();

        // Initialize DataTables with proper sequencing
        initDataTables();

        // Single feather icons render for both
        safeFeatherRender();
      });

      // Safe feather rendering function
      function safeFeatherRender() {
        try {
          if (window.feather) {
            feather.replace();
          }
        } catch (e) {
          console.warn("Feather icons render issue:", e);
        }
      }

      class FuturisticSidebar {
        constructor() {
          this.sidebar = document.getElementById("sidebar");
          this.toggleBtn = document.getElementById("toggleSidebar");
          this.isCollapsed = false;
          this.init();
        }

        init() {
          this.renderIcons();
          this.bindEvents();
          this.loadState();
        }

        bindEvents() {
          this.toggleBtn?.addEventListener("click", () => this.toggleSidebar());

          document.querySelectorAll("[data-collapse]").forEach((btn) => {
            btn.addEventListener("click", (e) => this.toggleSubmenu(e));
          });

          document.addEventListener("click", (e) => this.handleOutsideClick(e));
          document.addEventListener("keydown", (e) => this.handleKeyboard(e));
        }

        toggleSidebar() {
          this.isCollapsed = !this.isCollapsed;

          if (this.isCollapsed) {
            this.sidebar.classList.add("collapsed");
            this.sidebar.classList.remove("w-72");
            this.sidebar.classList.add("w-20");
            this.collapseAllSubmenus();
          } else {
            this.sidebar.classList.remove("collapsed");
            this.sidebar.classList.remove("w-20");
            this.sidebar.classList.add("w-72");
          }

          this.updateLogo();
          this.saveState();

          setTimeout(() => this.renderIcons(), 300);
        }

        toggleSubmenu(e) {
          if (this.isCollapsed) return;

          const btn = e.currentTarget;
          const key = btn.getAttribute("data-collapse");
          const panel = document.getElementById(`submenu-${key}`);
          const chevron = btn.querySelector('[data-feather="chevron-down"]');

          if (!panel.classList.contains("hidden")) {
            this.collapseAllSubmenus();
            return;
          }

          this.collapseAllSubmenus();
          panel.classList.remove("hidden");
          if (chevron) chevron.style.transform = "rotate(180deg)";

          setTimeout(() => this.renderIcons(), 150);
        }

        collapseAllSubmenus() {
          document.querySelectorAll('[id^="submenu-"]').forEach((panel) => {
            panel.classList.add("hidden");
          });
          document
            .querySelectorAll('[data-feather="chevron-down"]')
            .forEach((c) => {
              c.style.transform = "rotate(0deg)";
            });
        }

        handleOutsideClick(e) {
          if (!this.sidebar.contains(e.target) && !this.isCollapsed) {
            this.collapseAllSubmenus();
          }
        }

        handleKeyboard(e) {
          if (e.key === "Escape" && !this.isCollapsed)
            this.collapseAllSubmenus();
        }

        updateLogo() {
          const logo = document.getElementById("logo");
          if (!logo) return;
          try {
            if (this.isCollapsed) {
              logo.src = "{% static 'images/barkat_logo_b.svg' %}";
            } else {
              logo.src = "{% static 'images/barkat_logo.svg' %}";
            }
          } catch (e) {}
        }
        renderIcons() {
          safeFeatherRender();
        }

        saveState() {
          try {
            localStorage.setItem("sidebarCollapsed", this.isCollapsed);
          } catch (e) {}
        }

        loadState() {
          try {
            const savedState = localStorage.getItem("sidebarCollapsed");
            if (savedState === "true") {
              this.isCollapsed = true;
              this.sidebar.classList.add("collapsed", "w-20");
              this.sidebar.classList.remove("w-72");
              this.updateLogo();
            }
          } catch (e) {}
        }
      }

      function safeFeatherRender() {
        try {
          if (window.feather && !window.featherRendering) {
            window.featherRendering = true;
            feather.replace();
            setTimeout(() => {
              window.featherRendering = false;
            }, 100);
          }
        } catch (e) {}
      }

      window.addEventListener("resize", () => {
        setTimeout(() => {
          try {
            if (window.feather) window.feather.replace();
          } catch (e) {}
        }, 100);
      });