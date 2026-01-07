/**
 * Toast Service Tests
 * @module services/__tests__/toast-service
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showToast, showSuccess, showError, showWarning, showInfo } from '../toast-service.js';

describe('ToastService', () => {
  let originalSwal;
  let originalToastr;

  beforeEach(() => {
    // Store original globals
    originalSwal = window.Swal;
    originalToastr = window.toastr;

    // Reset mocks
    vi.clearAllMocks();

    // Setup Swal mock
    window.Swal = {
      fire: vi.fn()
    };

    // Setup toastr mock
    window.toastr = {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn()
    };
  });

  afterEach(() => {
    // Restore original globals
    window.Swal = originalSwal;
    window.toastr = originalToastr;
  });

  describe('showToast', () => {
    it('should show toast with message and type', () => {
      showToast('Test message', 'success');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          toast: true,
          icon: 'success',
          title: 'Test message'
        })
      );
    });

    it('should handle reversed legacy order (type, message)', () => {
      showToast('success', 'Test message');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          toast: true,
          icon: 'success',
          title: 'Test message'
        })
      );
    });

    it('should normalize danger to error', () => {
      showToast('Test message', 'danger');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          icon: 'error'
        })
      );
    });

    it('should normalize notice to info', () => {
      showToast('Test message', 'notice');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          icon: 'info'
        })
      );
    });

    it('should default to info when no type provided', () => {
      showToast('Test message');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          icon: 'info'
        })
      );
    });

    it('should handle 3-string signature (title, message, type)', () => {
      showToast('Custom Title', 'Test message', 'warning');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          toast: true,
          icon: 'warning',
          title: 'Custom Title',
          text: 'Test message'
        })
      );
    });

    it('should handle 3-string signature (icon, title, text)', () => {
      showToast('success', 'Success Title', 'Operation completed');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          toast: true,
          icon: 'success',
          title: 'Success Title',
          text: 'Operation completed'
        })
      );
    });

    it('should pass custom duration option', () => {
      showToast('Test message', 'info', { duration: 5000 });

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          timer: 5000
        })
      );
    });

    it('should pass custom position option', () => {
      showToast('Test message', 'info', { position: 'bottom-start' });

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          position: 'bottom-start'
        })
      );
    });

    it('should fall back to toastr when Swal is undefined', () => {
      window.Swal = undefined;

      showToast('Test message', 'success');

      expect(window.toastr.success).toHaveBeenCalledWith('Test message', undefined);
    });

    it('should handle case-insensitive types', () => {
      showToast('Test message', 'SUCCESS');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          icon: 'success'
        })
      );
    });
  });

  describe('showSuccess', () => {
    it('should call showToast with success type', () => {
      showSuccess('Success message');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          icon: 'success',
          title: 'Success message'
        })
      );
    });

    it('should pass options through', () => {
      showSuccess('Success message', { duration: 5000 });

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          timer: 5000
        })
      );
    });
  });

  describe('showError', () => {
    it('should call showToast with error type', () => {
      showError('Error message');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          icon: 'error',
          title: 'Error message'
        })
      );
    });
  });

  describe('showWarning', () => {
    it('should call showToast with warning type', () => {
      showWarning('Warning message');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          icon: 'warning',
          title: 'Warning message'
        })
      );
    });
  });

  describe('showInfo', () => {
    it('should call showToast with info type', () => {
      showInfo('Info message');

      expect(window.Swal.fire).toHaveBeenCalledWith(
        expect.objectContaining({
          icon: 'info',
          title: 'Info message'
        })
      );
    });
  });

  describe('window exposure', () => {
    it('should expose showToast on window', () => {
      expect(typeof window.showToast).toBe('function');
    });

    it('should expose ToastService on window', () => {
      expect(window.ToastService).toBeDefined();
      expect(typeof window.ToastService.show).toBe('function');
      expect(typeof window.ToastService.success).toBe('function');
      expect(typeof window.ToastService.error).toBe('function');
      expect(typeof window.ToastService.warning).toBe('function');
      expect(typeof window.ToastService.info).toBe('function');
    });
  });

  describe('fallback chain', () => {
    it('should use toastr when Swal is undefined', () => {
      window.Swal = undefined;

      showToast('Test message', 'error');

      expect(window.toastr.error).toHaveBeenCalled();
    });

    it('should create Bootstrap toast when both Swal and toastr are undefined', () => {
      window.Swal = undefined;
      window.toastr = undefined;

      // Should not throw
      expect(() => showToast('Test message', 'success')).not.toThrow();

      // Check that a toast container was created
      const container = document.querySelector('[data-role="toast-container"]');
      expect(container).toBeTruthy();

      // Cleanup
      container?.remove();
    });
  });
});
