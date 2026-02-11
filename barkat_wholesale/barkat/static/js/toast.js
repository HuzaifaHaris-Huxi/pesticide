   (function () {
        const backDrop = document.getElementById("toast-backdrop");

        function removeToast(el) {
          // animate out
          el.style.transition = "opacity .25s ease, transform .25s ease";
          el.style.opacity = "0";
          el.style.transform = "translateY(6px) scale(0.98)";
          setTimeout(() => {
            el.remove();
            // remove backdrop if no toasts remain
            if (!document.querySelector("[data-toast]")) {
              backDrop && backDrop.remove();
            }
          }, 260);
        }

        // Auto-dismiss after 3 seconds (per toast)
        document.querySelectorAll("[data-toast]").forEach((el) => {
          setTimeout(() => removeToast(el), 3000);
        });

        // OK button dismiss
        document.addEventListener("click", (e) => {
          const okBtn = e.target.closest("[data-action='toast-ok']");
          if (okBtn) {
            const toast = okBtn.closest("[data-toast]");
            if (toast) removeToast(toast);
          }
        });
      })();