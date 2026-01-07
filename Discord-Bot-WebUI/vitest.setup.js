/**
 * Vitest Global Setup
 * Configure global test environment and mocks
 */

import { expect, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

// Mock window.InitSystem
globalThis.window = globalThis.window || {};
window.InitSystem = {
  register: vi.fn(),
  init: vi.fn(),
  isInitialized: vi.fn(() => true)
};

// Mock window.EventDelegation
window.EventDelegation = {
  register: vi.fn(),
  unregister: vi.fn(),
  trigger: vi.fn()
};

// Mock localStorage
const localStorageMock = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn()
};
globalThis.localStorage = localStorageMock;

// Mock sessionStorage
const sessionStorageMock = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn()
};
globalThis.sessionStorage = sessionStorageMock;

// Mock fetch
globalThis.fetch = vi.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({}),
    text: () => Promise.resolve(''),
    headers: new Headers()
  })
);

// Mock CSRF token
window.CSRF_TOKEN = 'test-csrf-token';

// Mock jQuery (minimal)
window.$ = vi.fn((selector) => {
  const mockElement = {
    length: 1,
    on: vi.fn().mockReturnThis(),
    off: vi.fn().mockReturnThis(),
    click: vi.fn().mockReturnThis(),
    html: vi.fn().mockReturnThis(),
    text: vi.fn().mockReturnThis(),
    val: vi.fn().mockReturnThis(),
    attr: vi.fn().mockReturnThis(),
    data: vi.fn().mockReturnThis(),
    addClass: vi.fn().mockReturnThis(),
    removeClass: vi.fn().mockReturnThis(),
    toggleClass: vi.fn().mockReturnThis(),
    hasClass: vi.fn(() => false),
    show: vi.fn().mockReturnThis(),
    hide: vi.fn().mockReturnThis(),
    fadeIn: vi.fn().mockReturnThis(),
    fadeOut: vi.fn().mockReturnThis(),
    find: vi.fn().mockReturnThis(),
    parent: vi.fn().mockReturnThis(),
    parents: vi.fn().mockReturnThis(),
    closest: vi.fn().mockReturnThis(),
    children: vi.fn().mockReturnThis(),
    append: vi.fn().mockReturnThis(),
    prepend: vi.fn().mockReturnThis(),
    remove: vi.fn().mockReturnThis(),
    empty: vi.fn().mockReturnThis(),
    each: vi.fn().mockReturnThis(),
    prop: vi.fn().mockReturnThis(),
    is: vi.fn(() => false)
  };
  return mockElement;
});
window.$.ajax = vi.fn(() => Promise.resolve({}));
window.$.fn = {};
window.jQuery = window.$;

// Mock Bootstrap
window.bootstrap = {
  Modal: vi.fn().mockImplementation(() => ({
    show: vi.fn(),
    hide: vi.fn(),
    dispose: vi.fn()
  })),
  Tooltip: vi.fn().mockImplementation(() => ({
    show: vi.fn(),
    hide: vi.fn(),
    dispose: vi.fn()
  })),
  Popover: vi.fn().mockImplementation(() => ({
    show: vi.fn(),
    hide: vi.fn(),
    dispose: vi.fn()
  })),
  Dropdown: vi.fn().mockImplementation(() => ({
    show: vi.fn(),
    hide: vi.fn(),
    dispose: vi.fn()
  }))
};

// Add getInstance method to Modal
window.bootstrap.Modal.getInstance = vi.fn(() => ({
  show: vi.fn(),
  hide: vi.fn(),
  dispose: vi.fn()
}));

// Mock SweetAlert2
window.Swal = {
  fire: vi.fn(() => Promise.resolve({ isConfirmed: true, value: '' })),
  close: vi.fn(),
  isVisible: vi.fn(() => false)
};

// Mock toastr
globalThis.toastr = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
  options: {}
};

// Mock ECSTheme
window.ECSTheme = {
  getColor: vi.fn((key) => {
    const colors = {
      primary: '#0d6efd',
      secondary: '#6c757d',
      success: '#198754',
      danger: '#dc3545',
      warning: '#ffc107',
      info: '#0dcaf0'
    };
    return colors[key] || '#000000';
  })
};

// Mock SocketManager
window.SocketManager = {
  getSocket: vi.fn(() => ({
    connected: true,
    emit: vi.fn(),
    on: vi.fn(),
    off: vi.fn()
  })),
  isOptimisticallyConnected: vi.fn(() => true),
  onConnect: vi.fn(),
  onDisconnect: vi.fn(),
  on: vi.fn(),
  off: vi.fn()
};

// Mock ModalManager
window.ModalManager = {
  show: vi.fn(),
  hide: vi.fn(),
  register: vi.fn()
};

// Reset all mocks before each test
beforeEach(() => {
  vi.clearAllMocks();
  localStorageMock.getItem.mockClear();
  localStorageMock.setItem.mockClear();
});

// Custom matchers
expect.extend({
  toBeVisible(element) {
    const pass = element && element.style?.display !== 'none' && !element.classList?.contains('d-none');
    return {
      pass,
      message: () => `expected element ${pass ? 'not ' : ''}to be visible`
    };
  },
  toHaveClass(element, className) {
    const pass = element && element.classList?.contains(className);
    return {
      pass,
      message: () => `expected element ${pass ? 'not ' : ''}to have class "${className}"`
    };
  }
});
