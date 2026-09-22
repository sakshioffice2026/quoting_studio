/*!
 * FenestraOne - client-side form validation
 *
 * Form:   <form data-validate novalidate> ... </form>
 * Field:  <input data-rules="required|email|maxlen:254" data-label="Email">
 * Rules:  required | minlen:n | maxlen:n | email | phone | letters | strongpass | match:<fieldId>
 * Group:  <form data-require-one="phone,email" data-require-one-msg="...">
 * Alert:  <div data-form-alert></div>   (optional summary box inside the form)
 * Extras: data-toggle-password (show/hide button), data-loading="Saving..." (submit button text)
 */
(function () {
  'use strict';

  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  var PHONE_RE = /^\+?[0-9][0-9\s\-()]{5,19}$/;
  var LETTER_RE = /[A-Za-z\u00C0-\u024F\u0900-\u097F]/;

  function isSecret(el) {
    return el.type === 'password' || el.hasAttribute('data-toggle-password');
  }

  function getValue(el) {
    if (isSecret(el)) { return el.value; }
    return (el.value || '').trim();
  }

  function labelOf(el) {
    return el.getAttribute('data-label') || el.name || 'This field';
  }

  var RULES = {
    required: function (el, v, arg, name) {
      if (el.type === 'checkbox') { return el.checked ? '' : name + ' is required.'; }
      if (v !== '') { return ''; }
      if (el.tagName === 'SELECT') { return 'Please select ' + name.toLowerCase() + '.'; }
      return name + ' is required.';
    },
    minlen: function (el, v, arg, name) {
      return v.length < parseInt(arg, 10) ? name + ' must be at least ' + arg + ' characters.' : '';
    },
    maxlen: function (el, v, arg, name) {
      return v.length > parseInt(arg, 10) ? name + ' must be at most ' + arg + ' characters.' : '';
    },
    email: function (el, v) {
      return EMAIL_RE.test(v) ? '' : 'Enter a valid email address, e.g. name@company.com.';
    },
    phone: function (el, v) {
      var digits = v.replace(/\D/g, '');
      return (PHONE_RE.test(v) && digits.length >= 7 && digits.length <= 15)
        ? '' : 'Enter a valid phone number (7-15 digits, may start with +).';
    },
    letters: function (el, v, arg, name) {
      return LETTER_RE.test(v) ? '' : name + ' must contain letters.';
    },
    strongpass: function (el, v) {
      return (v.length >= 8 && /[A-Za-z]/.test(v) && /\d/.test(v))
        ? '' : 'Password must be at least 8 characters and include a letter and a number.';
    },
    match: function (el, v, arg) {
      var other = document.getElementById(arg);
      return (other && other.value === el.value)
        ? '' : (el.getAttribute('data-match-msg') || 'Values do not match.');
    }
  };

  function parseRules(el) {
    return (el.getAttribute('data-rules') || '').split('|').filter(Boolean).map(function (r) {
      var i = r.indexOf(':');
      return i === -1 ? { name: r, arg: '' } : { name: r.slice(0, i), arg: r.slice(i + 1) };
    });
  }

  function errorBox(el) {
    var id = (el.id || el.name) + '-error';
    var box = document.getElementById(id);
    if (!box) {
      box = document.createElement('div');
      box.id = id;
      box.className = 'field-error';
      box.setAttribute('role', 'alert');
      var anchor = el.closest('.pw-wrap') || el;
      anchor.insertAdjacentElement('afterend', box);
      el.setAttribute('aria-describedby', id);
    }
    return box;
  }

  function setError(el, msg) {
    var box = errorBox(el);
    if (msg) {
      el.classList.add('is-invalid');
      el.setAttribute('aria-invalid', 'true');
      box.textContent = msg;
      box.classList.add('show');
    } else {
      el.classList.remove('is-invalid');
      el.removeAttribute('aria-invalid');
      box.textContent = '';
      box.classList.remove('show');
    }
    return !msg;
  }

  function groupIds(form) {
    var raw = form.getAttribute('data-require-one');
    return raw ? raw.split(',').map(function (s) { return s.trim(); }) : [];
  }

  function groupError(form, el) {
    var ids = groupIds(form);
    if (ids.indexOf(el.id) === -1) { return ''; }
    var anyFilled = ids.some(function (id) {
      var f = document.getElementById(id);
      return f && getValue(f) !== '';
    });
    return anyFilled ? '' : (form.getAttribute('data-require-one-msg') || 'Fill in at least one of these fields.');
  }

  function validateField(el) {
    if (el.disabled) { return true; }
    var v = getValue(el);
    var name = labelOf(el);
    var rules = parseRules(el);
    var msg = '';

    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (r.name !== 'required' && v === '' && el.type !== 'checkbox') { continue; }
      var fn = RULES[r.name];
      if (!fn) { continue; }
      msg = fn(el, v, r.arg, name);
      if (msg) { break; }
    }

    if (!msg && el.form) { msg = groupError(el.form, el); }
    return setError(el, msg);
  }

  function fieldsOf(form) {
    return Array.prototype.slice.call(form.querySelectorAll('[data-rules]'));
  }

  function validateForm(form) {
    var first = null;
    fieldsOf(form).forEach(function (el) {
      if (!validateField(el) && !first) { first = el; }
    });
    return first;
  }

  function isValidatedField(el) {
    return el && el.matches && el.matches('form[data-validate] [data-rules]');
  }

  function revalidateDependents(el) {
    var form = el.form;
    if (!form) { return; }
    fieldsOf(form).forEach(function (other) {
      if (other === el) { return; }
      var linked = (other.getAttribute('data-rules') || '').indexOf('match:' + el.id) !== -1;
      var grouped = groupIds(form).indexOf(el.id) !== -1 && groupIds(form).indexOf(other.id) !== -1;
      if ((linked && getValue(other) !== '') || (grouped && other.classList.contains('is-invalid'))) {
        validateField(other);
      }
    });
  }

  document.addEventListener('focusout', function (e) {
    var el = e.target;
    if (!isValidatedField(el)) { return; }
    if (!isSecret(el) && el.type !== 'checkbox' && el.tagName !== 'SELECT' && el.value) {
      el.value = el.value.trim();
    }
    validateField(el);
    revalidateDependents(el);
  });

  document.addEventListener('input', function (e) {
    var el = e.target;
    if (!isValidatedField(el)) { return; }
    if ((el.getAttribute('data-rules') || '').indexOf('phone') !== -1) {
      var cleaned = el.value.replace(/[^0-9+\-()\s]/g, '');
      if (cleaned !== el.value) { el.value = cleaned; }
    }
    if (el.classList.contains('is-invalid')) { validateField(el); }
    revalidateDependents(el);
  });

  document.addEventListener('change', function (e) {
    var el = e.target;
    if (!isValidatedField(el)) { return; }
    validateField(el);
    revalidateDependents(el);
  });

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('form[data-validate]')) { return; }

    fieldsOf(form).forEach(function (el) {
      if (!isSecret(el) && el.type !== 'checkbox' && el.tagName !== 'SELECT' && el.value) {
        el.value = el.value.trim();
      }
    });

    var first = validateForm(form);
    var alertBox = form.querySelector('[data-form-alert]');

    if (first) {
      e.preventDefault();
      e.stopPropagation();
      if (alertBox) {
        alertBox.textContent = 'Please fix the highlighted fields.';
        alertBox.classList.add('show');
      }
      first.focus();
      if (first.scrollIntoView) { first.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
      return;
    }

    if (alertBox) { alertBox.classList.remove('show'); }

    var btn = form.querySelector('[type="submit"]');
    if (btn && !btn.hasAttribute('data-orig')) {
      btn.setAttribute('data-orig', btn.innerHTML);
      setTimeout(function () {
        btn.disabled = true;
        if (btn.getAttribute('data-loading')) { btn.textContent = btn.getAttribute('data-loading'); }
      }, 0);
    }
  }, true);

  window.addEventListener('pageshow', function () {
    document.querySelectorAll('form[data-validate] [type="submit"][data-orig]').forEach(function (btn) {
      btn.disabled = false;
      btn.innerHTML = btn.getAttribute('data-orig');
      btn.removeAttribute('data-orig');
    });
  });

  function initPasswordToggles() {
    document.querySelectorAll('input[data-toggle-password]').forEach(function (input) {
      if (input.parentNode.classList.contains('pw-wrap')) { return; }
      var wrap = document.createElement('div');
      wrap.className = 'pw-wrap';
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pw-toggle';
      btn.textContent = 'Show';
      btn.setAttribute('aria-label', 'Show password');
      btn.addEventListener('click', function () {
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.textContent = show ? 'Hide' : 'Show';
        btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      });
      wrap.appendChild(btn);
    });
  }

  function init() {
    document.querySelectorAll('form[data-validate]').forEach(function (form) {
      form.setAttribute('novalidate', 'novalidate');
    });
    initPasswordToggles();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.FormValidation = { validateField: validateField, validateForm: validateForm };
})();
