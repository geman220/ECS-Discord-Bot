/**
 * Event Delegation Core Tests
 * @module event-delegation/__tests__/core
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EventDelegation } from '../core.js';

describe('EventDelegation', () => {
  beforeEach(() => {
    // Clear all handlers before each test
    EventDelegation.handlers.clear();
    EventDelegation.duplicates.clear();
    EventDelegation.debug = false;
    EventDelegation.resetStats();
    vi.clearAllMocks();
  });

  describe('register', () => {
    it('should register a handler function', () => {
      const handler = vi.fn();
      EventDelegation.register('test-action', handler);

      expect(EventDelegation.isRegistered('test-action')).toBe(true);
    });

    it('should increment handlersRegistered stat', () => {
      EventDelegation.register('action1', vi.fn());
      EventDelegation.register('action2', vi.fn());

      expect(EventDelegation.stats.handlersRegistered).toBe(2);
    });

    it('should warn when overwriting an existing handler', () => {
      const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      EventDelegation.register('duplicate-action', vi.fn());
      EventDelegation.register('duplicate-action', vi.fn());

      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('WARNING: Handler for action "duplicate-action" is being overwritten')
      );
      expect(EventDelegation.duplicates.has('duplicate-action')).toBe(true);

      consoleSpy.mockRestore();
    });

    it('should reject non-function handlers', () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      EventDelegation.register('bad-action', 'not a function');

      expect(EventDelegation.isRegistered('bad-action')).toBe(false);
      expect(consoleSpy).toHaveBeenCalled();

      consoleSpy.mockRestore();
    });

    it('should apply preventDefault option', () => {
      const handler = vi.fn();
      EventDelegation.register('prevent-action', handler, { preventDefault: true });

      const mockEvent = { preventDefault: vi.fn(), stopPropagation: vi.fn() };
      const mockElement = document.createElement('button');

      // Get the wrapped handler and call it
      const wrappedHandler = EventDelegation.handlers.get('prevent-action');
      wrappedHandler(mockElement, mockEvent);

      expect(mockEvent.preventDefault).toHaveBeenCalled();
      expect(handler).toHaveBeenCalledWith(mockElement, mockEvent);
    });

    it('should apply stopPropagation option', () => {
      const handler = vi.fn();
      EventDelegation.register('stop-action', handler, { stopPropagation: true });

      const mockEvent = { preventDefault: vi.fn(), stopPropagation: vi.fn() };
      const mockElement = document.createElement('button');

      const wrappedHandler = EventDelegation.handlers.get('stop-action');
      wrappedHandler(mockElement, mockEvent);

      expect(mockEvent.stopPropagation).toHaveBeenCalled();
    });

    it('should log when debug is enabled', () => {
      const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
      EventDelegation.debug = true;

      EventDelegation.register('debug-action', vi.fn());

      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('Registered handler: debug-action')
      );

      consoleSpy.mockRestore();
    });
  });

  describe('unregister', () => {
    it('should remove a registered handler', () => {
      EventDelegation.register('remove-action', vi.fn());
      expect(EventDelegation.isRegistered('remove-action')).toBe(true);

      EventDelegation.unregister('remove-action');
      expect(EventDelegation.isRegistered('remove-action')).toBe(false);
    });

    it('should decrement handlersRegistered stat', () => {
      EventDelegation.register('temp-action', vi.fn());
      expect(EventDelegation.stats.handlersRegistered).toBe(1);

      EventDelegation.unregister('temp-action');
      expect(EventDelegation.stats.handlersRegistered).toBe(0);
    });

    it('should handle unregistering non-existent action gracefully', () => {
      expect(() => EventDelegation.unregister('non-existent')).not.toThrow();
    });
  });

  describe('isRegistered', () => {
    it('should return true for registered actions', () => {
      EventDelegation.register('check-action', vi.fn());
      expect(EventDelegation.isRegistered('check-action')).toBe(true);
    });

    it('should return false for unregistered actions', () => {
      expect(EventDelegation.isRegistered('unknown-action')).toBe(false);
    });
  });

  describe('getRegisteredActions', () => {
    it('should return array of registered action names', () => {
      EventDelegation.register('action-a', vi.fn());
      EventDelegation.register('action-b', vi.fn());
      EventDelegation.register('action-c', vi.fn());

      const actions = EventDelegation.getRegisteredActions();

      expect(actions).toContain('action-a');
      expect(actions).toContain('action-b');
      expect(actions).toContain('action-c');
      expect(actions).toHaveLength(3);
    });
  });

  describe('getDuplicates', () => {
    it('should return array of duplicate action names', () => {
      vi.spyOn(console, 'warn').mockImplementation(() => {});

      EventDelegation.register('dup1', vi.fn());
      EventDelegation.register('dup1', vi.fn());
      EventDelegation.register('dup2', vi.fn());
      EventDelegation.register('dup2', vi.fn());
      EventDelegation.register('unique', vi.fn());

      const duplicates = EventDelegation.getDuplicates();

      expect(duplicates).toContain('dup1');
      expect(duplicates).toContain('dup2');
      expect(duplicates).not.toContain('unique');
    });
  });

  describe('handleClick', () => {
    it('should call handler when clicking element with data-action', () => {
      const handler = vi.fn();
      EventDelegation.register('click-test', handler);

      const button = document.createElement('button');
      button.dataset.action = 'click-test';
      button.dataset.itemId = '123';
      document.body.appendChild(button);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: button, writable: false });

      EventDelegation.handleClick(event);

      expect(handler).toHaveBeenCalledWith(button, event);
      expect(EventDelegation.stats.eventsProcessed).toBe(1);

      button.remove();
    });

    it('should not call handler when no data-action attribute', () => {
      const handler = vi.fn();
      EventDelegation.register('no-match', handler);

      const button = document.createElement('button');
      document.body.appendChild(button);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: button, writable: false });

      EventDelegation.handleClick(event);

      expect(handler).not.toHaveBeenCalled();

      button.remove();
    });

    it('should handle errors gracefully', () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const errorHandler = vi.fn(() => { throw new Error('Test error'); });
      EventDelegation.register('error-action', errorHandler);

      const button = document.createElement('button');
      button.dataset.action = 'error-action';
      document.body.appendChild(button);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: button, writable: false });

      expect(() => EventDelegation.handleClick(event)).not.toThrow();
      expect(EventDelegation.stats.errorsEncountered).toBe(1);

      consoleSpy.mockRestore();
      button.remove();
    });

    it('should find action on parent element', () => {
      const handler = vi.fn();
      EventDelegation.register('parent-action', handler);

      const parent = document.createElement('div');
      parent.dataset.action = 'parent-action';
      const child = document.createElement('span');
      parent.appendChild(child);
      document.body.appendChild(parent);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: child, writable: false });

      EventDelegation.handleClick(event);

      expect(handler).toHaveBeenCalledWith(parent, event);

      parent.remove();
    });
  });

  describe('handleChange', () => {
    it('should call handler for data-on-change elements', () => {
      const handler = vi.fn();
      EventDelegation.register('change-test', handler);

      const select = document.createElement('select');
      select.dataset.onChange = 'change-test';
      document.body.appendChild(select);

      const event = new Event('change', { bubbles: true });
      Object.defineProperty(event, 'target', { value: select, writable: false });

      EventDelegation.handleChange(event);

      expect(handler).toHaveBeenCalledWith(select, event);

      // Use parentElement.removeChild to avoid happy-dom's select.remove() quirk
      select.parentElement?.removeChild(select);
    });
  });

  describe('handleInput', () => {
    it('should call handler for data-on-input elements', () => {
      const handler = vi.fn();
      EventDelegation.register('input-test', handler);

      const input = document.createElement('input');
      input.dataset.onInput = 'input-test';
      document.body.appendChild(input);

      const event = new Event('input', { bubbles: true });
      Object.defineProperty(event, 'target', { value: input, writable: false });

      EventDelegation.handleInput(event);

      expect(handler).toHaveBeenCalledWith(input, event);

      input.parentElement?.removeChild(input);
    });
  });

  describe('handleSubmit', () => {
    it('should call handler for data-on-submit forms', () => {
      const handler = vi.fn();
      EventDelegation.register('submit-test', handler);

      const form = document.createElement('form');
      form.dataset.onSubmit = 'submit-test';
      document.body.appendChild(form);

      const event = new Event('submit', { bubbles: true });
      Object.defineProperty(event, 'target', { value: form, writable: false });

      EventDelegation.handleSubmit(event);

      expect(handler).toHaveBeenCalledWith(form, event);

      form.parentElement?.removeChild(form);
    });
  });

  describe('stats and debug', () => {
    it('should track statistics correctly', () => {
      EventDelegation.register('stat-action', vi.fn());

      const button = document.createElement('button');
      button.dataset.action = 'stat-action';
      document.body.appendChild(button);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: button, writable: false });

      EventDelegation.handleClick(event);
      EventDelegation.handleClick(event);

      const stats = EventDelegation.getStats();
      expect(stats.handlersRegistered).toBe(1);
      expect(stats.eventsProcessed).toBe(2);
      expect(stats.registeredActions).toBe(1);

      button.remove();
    });

    it('should reset stats correctly', () => {
      EventDelegation.stats.eventsProcessed = 100;
      EventDelegation.stats.errorsEncountered = 5;

      EventDelegation.resetStats();

      expect(EventDelegation.stats.eventsProcessed).toBe(0);
      expect(EventDelegation.stats.errorsEncountered).toBe(0);
    });

    it('should enable and disable debug mode', () => {
      expect(EventDelegation.debug).toBe(false);

      EventDelegation.enableDebug();
      expect(EventDelegation.debug).toBe(true);

      EventDelegation.disableDebug();
      expect(EventDelegation.debug).toBe(false);
    });
  });

  describe('window exposure', () => {
    it('should expose EventDelegation on window', () => {
      expect(window.EventDelegation).toBeDefined();
      expect(window.EventDelegation.register).toBeDefined();
      expect(window.EventDelegation.unregister).toBeDefined();
    });
  });
});
