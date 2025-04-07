/**
 * Example Socket.IO client code for React Native
 * 
 * This demonstrates how to connect to the live reporting Socket.IO server
 * and handle events properly.
 * 
 * UPDATED: Now includes explicit handling of authentication_success events
 * and proper session management to fix disconnection issues.
 */

import io from 'socket.io-client';

class LiveReportingService {
  constructor() {
    this.socket = null;
    this.matchId = null;
    this.teamId = null;
    this.listeners = {};
    this.connected = false;
    this.authenticated = false;
    this.connectionAttempts = 0;
    this.maxConnectionAttempts = 3;
  }

  connect(serverUrl, authToken) {
    // Return a promise to allow callers to know when authentication is complete
    return new Promise((resolve, reject) => {
      // Clean up any existing connection
      if (this.socket) {
        this.disconnect();
      }
      
      this.connectionAttempts++;

      // Remove any 'Bearer ' prefix if present in the token
      const cleanToken = authToken.replace(/^Bearer\s+/i, '');
      console.log('Connecting to Socket.IO server:', `${serverUrl}/live`);
      
      // Create socket connection - send token in multiple ways for compatibility
      this.socket = io(`${serverUrl}/live`, {
        // Include token in query parameters
        query: { token: cleanToken },
        
        // Include token in auth object
        auth: { token: cleanToken },
        
        // Include token in headers
        extraHeaders: {
          'Authorization': `Bearer ${cleanToken}`
        },
        
        path: '/socket.io',
        transports: ['websocket'],
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
        timeout: 10000
      });
      
      // Set up connection event handlers
      this.socket.on('connect', () => {
        console.log('Socket.IO connected successfully!');
        this.connected = true;
        this._notifyListeners('connect');
        
        // Set up an authentication timeout
        const authTimeout = setTimeout(() => {
          if (!this.authenticated) {
            console.error('Authentication timed out after 5 seconds');
            if (this.connectionAttempts < this.maxConnectionAttempts) {
              console.log(`Retrying connection (attempt ${this.connectionAttempts}/${this.maxConnectionAttempts})...`);
              this.socket.disconnect();
              this.connect(serverUrl, authToken).then(resolve).catch(reject);
            } else {
              reject(new Error('Authentication timed out after multiple attempts'));
            }
          }
        }, 5000);
        
        // Listen specifically for authentication success event
        this.socket.on('authentication_success', (data) => {
          console.log('Authentication successful:', data);
          clearTimeout(authTimeout);
          this.authenticated = true;
          this.connectionAttempts = 0; // Reset attempts on success
          this._notifyListeners('authentication_success', data);
          resolve(data); // Resolve the promise with auth data
          
          // Once authenticated, test the connection
          this.testConnection();
        });
      });
      
      this.socket.on('connect_error', (error) => {
        console.error('Socket.IO connection error:', error);
        this.connected = false;
        this._notifyListeners('error', {
          type: 'connection',
          message: error.message || 'Connection error'
        });
        
        // Retry connection if under the maximum attempts
        if (this.connectionAttempts < this.maxConnectionAttempts) {
          console.log(`Retrying connection (attempt ${this.connectionAttempts}/${this.maxConnectionAttempts})...`);
          setTimeout(() => {
            this.socket.disconnect();
            this.connect(serverUrl, authToken).then(resolve).catch(reject);
          }, 1000 * this.connectionAttempts); // Increasing backoff
        } else {
          reject(error);
        }
      });
      
      this.socket.on('disconnect', (reason) => {
        console.log('Socket.IO disconnected:', reason);
        this.connected = false;
        this.authenticated = false;
        this._notifyListeners('disconnect', { reason });
      });
      
      this.socket.on('error', (error) => {
        console.error('Socket.IO error:', error);
        this._notifyListeners('error', {
          type: 'socket',
          message: error.message || 'Socket error'
        });
      });
      
      // Set up game state event handlers
      this.socket.on('match_state', (data) => {
        console.log('Received match state');
        this._notifyListeners('match_state', data);
      });
      
      this.socket.on('active_reporters', (data) => {
        console.log('Received active reporters:', data.length);
        this._notifyListeners('active_reporters', data);
      });
      
      this.socket.on('player_shifts', (data) => {
        console.log('Received player shifts:', data.length);
        this._notifyListeners('player_shifts', data);
      });
      
      // Set up live update event handlers
      this.socket.on('reporter_joined', (data) => {
        console.log('Reporter joined:', data.username);
        this._notifyListeners('reporter_joined', data);
      });
      
      this.socket.on('reporter_left', (data) => {
        console.log('Reporter left:', data.username);
        this._notifyListeners('reporter_left', data);
      });
      
      this.socket.on('score_updated', (data) => {
        console.log('Score updated:', data.home_score, '-', data.away_score);
        this._notifyListeners('score_updated', data);
      });
      
      this.socket.on('timer_updated', (data) => {
        console.log('Timer updated:', data.elapsed_seconds, 'seconds');
        this._notifyListeners('timer_updated', data);
      });
      
      this.socket.on('event_added', (data) => {
        console.log('Event added:', data.event?.event_type);
        this._notifyListeners('event_added', data);
      });
      
      this.socket.on('player_shift_updated', (data) => {
        console.log('Player shift updated:', data.player_name);
        this._notifyListeners('player_shift_updated', data);
      });
      
      this.socket.on('report_submitted', (data) => {
        console.log('Report submitted by:', data.submitted_by_name);
        this._notifyListeners('report_submitted', data);
      });
    });
  }
  
  disconnect() {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
      this.connected = false;
      this.authenticated = false;
      console.log('Socket.IO disconnected by user');
    }
    this.matchId = null;
    this.teamId = null;
  }
  
  testConnection() {
    if (!this.socket || !this.connected) {
      console.error('Cannot test connection: Socket not connected');
      return Promise.reject(new Error('Not connected'));
    }
    
    console.log('Testing Socket.IO connection...');
    
    return new Promise((resolve, reject) => {
      // Set a timeout in case the server doesn't respond
      const timeout = setTimeout(() => {
        reject(new Error('Test connection timeout'));
      }, 5000);
      
      this.socket.emit('test_connection', { clientTime: new Date().toISOString() }, (response) => {
        clearTimeout(timeout);
        console.log('Connection test response:', response);
        this._notifyListeners('connection_test', response);
        resolve(response);
      });
    });
  }
  
  ping() {
    if (!this.socket || !this.connected) {
      console.error('Cannot ping: Socket not connected');
      return Promise.reject(new Error('Not connected'));
    }
    
    return new Promise((resolve, reject) => {
      // Set a timeout in case the server doesn't respond
      const timeout = setTimeout(() => {
        reject(new Error('Ping timeout'));
      }, 5000);
      
      this.socket.emit('ping_server', {}, (response) => {
        clearTimeout(timeout);
        console.log('Ping server response:', response);
        this._notifyListeners('ping_response', response);
        resolve(response);
      });
    });
  }
  
  joinMatch(matchId, teamId) {
    if (!this.socket || !this.connected || !this.authenticated) {
      console.error('Cannot join match: Socket not connected or not authenticated');
      return Promise.reject(new Error('Not connected or not authenticated'));
    }
    
    this.matchId = matchId;
    this.teamId = teamId;
    
    console.log(`Joining match ${matchId} for team ${teamId}`);
    
    return new Promise((resolve, reject) => {
      // Set up a one-time handler for match_state event
      const onMatchState = (state) => {
        this.socket.off('match_state', onMatchState);
        clearTimeout(timeout);
        resolve(state);
      };
      
      // Set up a timeout in case no match_state event is received
      const timeout = setTimeout(() => {
        this.socket.off('match_state', onMatchState);
        reject(new Error('Join match timeout - no match state received'));
      }, 5000);
      
      // Listen for match_state event (sent when joining a match)
      this.socket.once('match_state', onMatchState);
      
      // Send join_match event
      this.socket.emit('join_match', { match_id: matchId, team_id: teamId });
    });
  }
  
  leaveMatch() {
    if (!this.socket || !this.matchId) {
      return;
    }
    
    console.log(`Leaving match ${this.matchId}`);
    this.socket.emit('leave_match', { match_id: this.matchId });
    this.matchId = null;
    this.teamId = null;
  }
  
  updateScore(homeScore, awayScore) {
    if (!this.socket || !this.matchId || !this.connected || !this.authenticated) {
      console.error('Cannot update score: No active match or socket not connected');
      return Promise.reject(new Error('Not connected or not in a match'));
    }
    
    console.log(`Updating score to ${homeScore}-${awayScore}`);
    
    return new Promise((resolve) => {
      // Listen for score_updated event
      const onScoreUpdated = (data) => {
        this.removeListener('score_updated', onScoreUpdated);
        resolve(data);
      };
      
      this.addListener('score_updated', onScoreUpdated);
      
      this.socket.emit('update_score', {
        match_id: this.matchId,
        home_score: homeScore,
        away_score: awayScore
      });
      
      // Remove listener after a timeout in case we don't get a response
      setTimeout(() => {
        this.removeListener('score_updated', onScoreUpdated);
      }, 5000);
    });
  }
  
  updateTimer(elapsedSeconds, isRunning, period = null) {
    if (!this.socket || !this.matchId || !this.connected || !this.authenticated) {
      console.error('Cannot update timer: No active match or socket not connected');
      return Promise.reject(new Error('Not connected or not in a match'));
    }
    
    const data = {
      match_id: this.matchId,
      elapsed_seconds: elapsedSeconds,
      is_running: isRunning
    };
    
    if (period) {
      data.period = period;
    }
    
    console.log(`Updating timer: ${elapsedSeconds}s, running: ${isRunning}`);
    
    return new Promise((resolve) => {
      // Listen for timer_updated event
      const onTimerUpdated = (data) => {
        this.removeListener('timer_updated', onTimerUpdated);
        resolve(data);
      };
      
      this.addListener('timer_updated', onTimerUpdated);
      
      this.socket.emit('update_timer', data);
      
      // Remove listener after a timeout in case we don't get a response
      setTimeout(() => {
        this.removeListener('timer_updated', onTimerUpdated);
      }, 5000);
    });
  }
  
  addEvent(eventData) {
    if (!this.socket || !this.matchId || !this.connected || !this.authenticated) {
      console.error('Cannot add event: No active match or socket not connected');
      return Promise.reject(new Error('Not connected or not in a match'));
    }
    
    console.log('Adding event:', eventData.event_type);
    
    return new Promise((resolve) => {
      // Listen for event_added event
      const onEventAdded = (data) => {
        this.removeListener('event_added', onEventAdded);
        resolve(data);
      };
      
      this.addListener('event_added', onEventAdded);
      
      this.socket.emit('add_event', {
        match_id: this.matchId,
        event: eventData
      });
      
      // Remove listener after a timeout in case we don't get a response
      setTimeout(() => {
        this.removeListener('event_added', onEventAdded);
      }, 5000);
    });
  }
  
  togglePlayerShift(playerId, isActive) {
    if (!this.socket || !this.matchId || !this.teamId || !this.connected || !this.authenticated) {
      console.error('Cannot toggle player shift: No active match/team or socket not connected');
      return Promise.reject(new Error('Not connected or not in a match'));
    }
    
    console.log(`Toggling player ${playerId} shift to ${isActive ? 'active' : 'inactive'}`);
    
    return new Promise((resolve) => {
      // Listen for player_shift_updated event
      const onShiftUpdated = (data) => {
        if (data.player_id === playerId) {
          this.removeListener('player_shift_updated', onShiftUpdated);
          resolve(data);
        }
      };
      
      this.addListener('player_shift_updated', onShiftUpdated);
      
      this.socket.emit('update_player_shift', {
        match_id: this.matchId,
        player_id: playerId,
        is_active: isActive,
        team_id: this.teamId
      });
      
      // Remove listener after a timeout in case we don't get a response
      setTimeout(() => {
        this.removeListener('player_shift_updated', onShiftUpdated);
      }, 5000);
    });
  }
  
  submitReport(notes = '') {
    if (!this.socket || !this.matchId || !this.connected || !this.authenticated) {
      console.error('Cannot submit report: No active match or socket not connected');
      return Promise.reject(new Error('Not connected or not in a match'));
    }
    
    console.log('Submitting final match report');
    
    return new Promise((resolve) => {
      // Listen for report_submitted event
      const onReportSubmitted = (data) => {
        this.removeListener('report_submitted', onReportSubmitted);
        resolve(data);
      };
      
      this.addListener('report_submitted', onReportSubmitted);
      
      this.socket.emit('submit_report', {
        match_id: this.matchId,
        report_data: { notes }
      });
      
      // Remove listener after a timeout in case we don't get a response
      setTimeout(() => {
        this.removeListener('report_submitted', onReportSubmitted);
      }, 5000);
    });
  }
  
  // Event listener management
  addListener(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
    return () => this.removeListener(event, callback);
  }
  
  removeListener(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    }
  }
  
  _notifyListeners(event, data) {
    if (this.listeners[event]) {
      this.listeners[event].forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error(`Error in ${event} listener:`, error);
        }
      });
    }
  }
}

// Usage example - React Native hooks approach
function useLiveReporting() {
  const [isConnected, setIsConnected] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [matchState, setMatchState] = useState(null);
  const [error, setError] = useState(null);
  const serviceRef = useRef(new LiveReportingService());
  
  useEffect(() => {
    const service = serviceRef.current;
    
    // Set up event listeners
    const unsubscribers = [
      service.addListener('connect', () => setIsConnected(true)),
      service.addListener('disconnect', () => {
        setIsConnected(false);
        setIsAuthenticated(false);
      }),
      service.addListener('authentication_success', () => {
        setIsAuthenticated(true);
        setError(null);
      }),
      service.addListener('match_state', (state) => setMatchState(state)),
      service.addListener('error', (err) => setError(err.message || 'An error occurred')),
      // Add more listeners as needed
    ];
    
    // Clean up on unmount
    return () => {
      // Remove event listeners
      unsubscribers.forEach(unsubscribe => unsubscribe());
      
      // Disconnect
      service.disconnect();
    };
  }, []);
  
  // Function to connect to server
  const connect = async (serverUrl, authToken) => {
    try {
      await serviceRef.current.connect(serverUrl, authToken);
      return true;
    } catch (error) {
      setError(error.message || 'Failed to connect');
      return false;
    }
  };
  
  // Function to join a match
  const joinMatch = async (matchId, teamId) => {
    try {
      const state = await serviceRef.current.joinMatch(matchId, teamId);
      setMatchState(state);
      return true;
    } catch (error) {
      setError(error.message || 'Failed to join match');
      return false;
    }
  };
  
  // Function to update score
  const updateScore = (homeScore, awayScore) => {
    return serviceRef.current.updateScore(homeScore, awayScore);
  };
  
  // Other functions...
  
  return {
    isConnected,
    isAuthenticated,
    matchState,
    error,
    connect,
    joinMatch,
    updateScore,
    // Return other functions...
  };
}

export default LiveReportingService;