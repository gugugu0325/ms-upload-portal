const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.static('public'));

const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*' } });

const rooms = new Map();

function randomIntInclusive(min, max) {
  min = Math.ceil(min);
  max = Math.floor(max);
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function getRoomStateForClient(room, safe=false) {
  return {
    range: room.range,
    started: room.started,
    players: room.players,
    turnIndex: room.turnIndex,
    history: room.history.slice(-100),
    hostId: room.hostId,
    ...(safe ? {} : { secret: room.secret })
  };
}

function nextTurn(room) {
  if (room.players.length === 0) {
    room.turnIndex = 0;
    return;
  }
  room.turnIndex = (room.turnIndex + 1) % room.players.length;
}

io.on('connection', (socket) => {
  let joinedRoomId = null;
  let playerName = null;

  socket.on('createRoom', ({ roomId, name, min=0, max=100 }) => {
    roomId = (roomId || '').trim().toUpperCase() || Math.random().toString(36).slice(2, 6).toUpperCase();
    name = (name || '').trim().slice(0, 20) || 'Player';
    if (rooms.has(roomId)) {
      socket.emit('errorMsg', '房間代碼已存在，請換一個或加入現有房間。');
      return;
    }
    const secret = randomIntInclusive(min, max);
    const room = {
      hostId: socket.id,
      range: { min, max },
      secret,
      started: false,
      players: [],
      turnIndex: 0,
      history: []
    };
    rooms.set(roomId, room);
    socket.join(roomId);
    joinedRoomId = roomId;
    playerName = name;
    room.players.push({ id: socket.id, name });
    io.to(roomId).emit('systemMsg', `${name} 建立了房間並加入。房間代碼：${roomId}`);
    io.to(roomId).emit('state', getRoomStateForClient(room, true));
    socket.emit('roomJoined', { roomId, youAreHost: true });
  });

  socket.on('joinRoom', ({ roomId, name }) => {
    roomId = (roomId || '').trim().toUpperCase();
    name = (name || '').trim().slice(0, 20) || 'Player';
    const room = rooms.get(roomId);
    if (!room) {
      socket.emit('errorMsg', '找不到該房間，請確認代碼是否正確。');
      return;
    }
    if (room.started && room.players.length >= 16) {
      socket.emit('errorMsg', '遊戲已開始，房間人數已滿。');
      return;
    }

    socket.join(roomId);
    joinedRoomId = roomId;
    playerName = name;
    room.players.push({ id: socket.id, name });
    io.to(roomId).emit('systemMsg', `${name} 加入了房間。`);
    io.to(roomId).emit('state', getRoomStateForClient(room, true));
    socket.emit('roomJoined', { roomId, youAreHost: room.hostId === socket.id });
  });

  socket.on('startGame', ({ roomId, min, max }) => {
    const room = rooms.get(roomId);
    if (!room) return;
    if (room.hostId !== socket.id) {
      socket.emit('errorMsg', '只有房主可以開始遊戲。');
      return;
    }
    room.range = { min: Number.isFinite(min) ? min : 0, max: Number.isFinite(max) ? max : 100 };
    if (room.range.min >= room.range.max) {
      socket.emit('errorMsg', '區間設定有誤，請確認最小值 < 最大值。');
      return;
    }
    room.secret = randomIntInclusive(room.range.min, room.range.max);
    room.started = true;
    room.turnIndex = 0;
    room.history = [];
    io.to(roomId).emit('systemMsg', `遊戲開始！起始區間：${room.range.min} ~ ${room.range.max}`);
    io.to(roomId).emit('state', getRoomStateForClient(room, true));
  });

  socket.on('guess', ({ roomId, guess }) => {
    const room = rooms.get(roomId);
    if (!room || !room.started) return;
    const playerIdx = room.players.findIndex(p => p.id === socket.id);
    if (playerIdx === -1) {
      socket.emit('errorMsg', '你不在這個房間內。');
      return;
    }
    if (room.players.length === 0) return;
    if (room.players[room.turnIndex]?.id !== socket.id) {
      socket.emit('errorMsg', '還沒輪到你喔！');
      return;
    }
    guess = parseInt(guess, 10);
    if (!Number.isFinite(guess)) {
      socket.emit('errorMsg', '請輸入有效的整數。');
      return;
    }
    if (guess <= room.range.min || guess >= room.range.max) {
      socket.emit('errorMsg', `請輸入在 (${room.range.min}, ${room.range.max}) 的數字（不含邊界）。`);
      return;
    }

    let result = 'higher';
    if (guess === room.secret) {
      result = 'hit';
    } else if (guess > room.secret) {
      result = 'lower';
    }

    let newMin = room.range.min;
    let newMax = room.range.max;
    if (result === 'higher') newMin = guess;
    if (result === 'lower') newMax = guess;

    const entry = { name: room.players[playerIdx].name, guess, result, newMin, newMax, ts: Date.now() };
    room.history.push(entry);

    if (result === 'hit') {
      room.started = false;
      io.to(roomId).emit('systemMsg', `🎉 ${room.players[playerIdx].name} 猜中答案 ${room.secret}！遊戲結束。`);
      io.to(roomId).emit('state', getRoomStateForClient(room, true));
      return;
    } else {
      room.range = { min: newMin, max: newMax };
      nextTurn(room);
      io.to(roomId).emit('playFeedback', entry);
      io.to(roomId).emit('state', getRoomStateForClient(room, true));
    }
  });

  socket.on('chat', ({ roomId, text }) => {
    const room = rooms.get(roomId);
    if (!room) return;
    text = (text || '').toString().slice(0, 200);
    if (!text.trim()) return;
    io.to(roomId).emit('chat', { name: playerName || 'Player', text, ts: Date.now() });
  });

  socket.on('kick', ({ roomId, targetId }) => {
    const room = rooms.get(roomId);
    if (!room) return;
    if (room.hostId !== socket.id) {
      socket.emit('errorMsg', '只有房主可以踢人。');
      return;
    }
    const idx = room.players.findIndex(p => p.id === targetId);
    if (idx !== -1) {
      const [removed] = room.players.splice(idx, 1);
      io.to(roomId).emit('systemMsg', `${removed.name} 被房主移出房間。`);
      io.to(roomId).emit('state', getRoomStateForClient(room, true));
      const targetSocket = io.sockets.sockets.get(targetId);
      if (targetSocket) targetSocket.leave(roomId);
      io.to(targetId).emit('errorMsg', '你已被房主移出房間。');
    }
  });

  socket.on('disconnect', () => {
    if (!joinedRoomId) return;
    const room = rooms.get(joinedRoomId);
    if (!room) return;
    const idx = room.players.findIndex(p => p.id === socket.id);
    if (idx !== -1) {
      const [removed] = room.players.splice(idx, 1);
      io.to(joinedRoomId).emit('systemMsg', `${removed.name} 已離開。`);
      if (room.hostId === socket.id) {
        room.hostId = room.players[0]?.id || null;
        if (room.hostId) {
          io.to(joinedRoomId).emit('systemMsg', `房主已轉移給 ${room.players[0].name}。`);
        }
      }
      if (room.turnIndex >= room.players.length) {
        room.turnIndex = 0;
      }
    }
    if (room.players.length === 0) {
      rooms.delete(joinedRoomId);
    } else {
      io.to(joinedRoomId).emit('state', getRoomStateForClient(room, true));
    }
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`Ultimate Password server running on http://localhost:${PORT}`);
});
