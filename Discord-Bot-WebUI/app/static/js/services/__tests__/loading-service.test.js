/**
 * Loading Service Tests
 *
 * @module services/__tests__/loading-service.test
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { showLoading, hideLoading, showLoadingModal, hideLoadingModal } from '../loading-service.js';

describe('LoadingService', () => {
    let mockSwal;
    let mockBootstrap;

    beforeEach(() => {
        // Reset DOM
        document.body.innerHTML = '';

        // Mock SweetAlert2
        mockSwal = {
            fire: vi.fn().mockResolvedValue({}),
            close: vi.fn()
        };
        window.Swal = mockSwal;

        // Mock Bootstrap Modal
        mockBootstrap = {
            Modal: vi.fn().mockImplementation(() => ({
                show: vi.fn(),
                hide: vi.fn()
            }))
        };
        mockBootstrap.Modal.getInstance = vi.fn().mockReturnValue(null);
        window.Modal = mockBootstrap.Modal;
    });

    afterEach(() => {
        delete window.Swal;
        delete window.Modal;
        vi.clearAllMocks();
    });

    describe('showLoading', () => {
        it('should show loading with SweetAlert2 when available', () => {
            const id = showLoading();

            expect(mockSwal.fire).toHaveBeenCalled();
            expect(id).toMatch(/^swal-\d+$/);
        });

        it('should accept a title string', () => {
            showLoading('Processing...');

            expect(mockSwal.fire).toHaveBeenCalledWith(
                expect.objectContaining({
                    title: 'Processing...'
                })
            );
        });

        it('should accept options object', () => {
            showLoading({ title: 'Custom Title', message: 'Please wait' });

            expect(mockSwal.fire).toHaveBeenCalledWith(
                expect.objectContaining({
                    title: 'Custom Title'
                })
            );
        });

        it('should show element loading when target is an element', () => {
            const element = document.createElement('div');
            document.body.appendChild(element);

            const id = showLoading(element);

            expect(element.classList.contains('is-loading')).toBe(true);
            expect(element.dataset.loading).toBe('true');
            expect(id).toMatch(/^element-\d+$/);
        });

        it('should show element loading when target is a selector', () => {
            const element = document.createElement('div');
            element.id = 'test-element';
            document.body.appendChild(element);

            const id = showLoading('#test-element');

            expect(element.classList.contains('is-loading')).toBe(true);
            expect(id).toMatch(/^element-\d+$/);
        });
    });

    describe('hideLoading', () => {
        it('should return a loading ID when showing swal loading', () => {
            const id = showLoading();
            // Swal.fire was called
            expect(mockSwal.fire).toHaveBeenCalled();
            expect(id).toMatch(/^swal-\d+$/);
        });

        it('should not throw when hideLoading called without args', () => {
            showLoading();
            // hideLoading without args should not throw
            expect(() => hideLoading()).not.toThrow();
        });

        it('should remove loading class from element', () => {
            const element = document.createElement('div');
            element.classList.add('is-loading');
            element.dataset.loading = 'true';
            document.body.appendChild(element);

            hideLoading(element);

            expect(element.classList.contains('is-loading')).toBe(false);
            expect(element.dataset.loading).toBe('false');
        });

        it('should hide element loading by selector', () => {
            const element = document.createElement('div');
            element.id = 'test-loading-element';
            element.classList.add('is-loading');
            element.dataset.loading = 'true';
            document.body.appendChild(element);

            hideLoading('#test-loading-element');

            expect(element.classList.contains('is-loading')).toBe(false);
        });
    });

    describe('showLoadingModal', () => {
        it('should create and show a Bootstrap modal', () => {
            const id = showLoadingModal('Loading', 'Please wait...');

            expect(id).toMatch(/^modal-\d+$/);
            const modal = document.getElementById('loadingModal');
            expect(modal).not.toBeNull();
        });

        it('should display title and message in modal', () => {
            showLoadingModal('Test Title', 'Test Message');

            const modal = document.getElementById('loadingModal');
            expect(modal.innerHTML).toContain('Test Title');
            expect(modal.innerHTML).toContain('Test Message');
        });
    });

    describe('hideLoadingModal', () => {
        it('should remove the loading modal from DOM', () => {
            showLoadingModal('Loading', 'Please wait...');
            expect(document.getElementById('loadingModal')).not.toBeNull();

            hideLoadingModal();
            expect(document.getElementById('loadingModal')).toBeNull();
        });
    });

    describe('window exposure', () => {
        it('should expose LoadingService on window', async () => {
            // Re-import to trigger window exposure
            await import('../loading-service.js');

            expect(window.LoadingService).toBeDefined();
            expect(typeof window.LoadingService.show).toBe('function');
            expect(typeof window.LoadingService.hide).toBe('function');
        });

        it('should expose showLoading on window', async () => {
            await import('../loading-service.js');

            expect(typeof window.showLoading).toBe('function');
            expect(typeof window.hideLoading).toBe('function');
        });
    });
});
