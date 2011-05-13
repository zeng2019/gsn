package gsn.wrappers.backlog;

import java.io.IOException;
import java.io.Serializable;
import java.io.UnsupportedEncodingException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.text.CharacterIterator;
import java.text.StringCharacterIterator;


/**
 * Defines a backlog message, used by the protocol communicated 
 * between the Python backlog program running on a CoreStation and
 * the {@link AsyncCoreStationClient} on side of GSN. It offers the
 * functionality to access the message format.
 * <p>
 * The binary message has the following format:
 * <ul><table border="1">
 * 	<tr>
 *   <th colspan="2">header</th>
 *   <th rowspan="2">payload</th>
 *  </tr>
 * 	<tr>
 *   <th>type</th>
 *   <th>timestamp</th>
 *  </tr>
 *  <tr>
 *   <td>1 byte</td>
 *   <td>8 bytes</td>
 *   <td>maximum MAX_PAYLOAD_SIZE bytes</td>
 *  </tr>
 * </table></ul>
 * 
 * There are three predefined message types:
 * <ul>
 * <li>ACK_MESSAGE_TYPE = 1: The acknowledge message type.
 *  This message type is used to acknowledge data messages.</li>
 * <li>PING_MESSAGE_TYPE = 2: The ping message type. This message
 *  type is used to ping a deployment, thus, requesting a
 *  PING_ACK_MESSAGE_TYPE.</li>
 * <li>PING_ACK_MESSAGE_TYPE = 3: The ping acknowledge message type.
 *  This message type is used to acknowledge a ping request.</li>
 * </ul>
 * 
 * Each plugin type used by {@link gsn.wrappers.BackLogWrapper BackLogWrapper} must
 * specify a unique message type, which has to be named here:
 * <ul>
 * <li>BACKLOG_COMMAND_MESSAGE_TYPE = 10: The backlog command message type.
 *  This message type is used to send/receive backlog command messages by the
 *  {@link gsn.wrappers.backlog.plugins.BackLogCommandPlugin BackLogCommandPlugin}.</li>
 * <li>TOS_MESSAGE_TYPE = 11: The TOS message type. This message
 *  type is used to send/receive TOS messages by the
 *  {@link gsn.wrappers.backlog.plugins.MigMessagePlugin MigMessagePlugin}.</li>
 * </ul>
 * 
 * @author	Tonio Gsell
 * 
 * @see gsn.wrappers.BackLogWrapper BackLogWrapper
 */
public class BackLogMessage {
	
	
	
	/* ##############################################################
	 * #                                                            #
	 * #        Add new message types for additional plugins.       #
	 */
	
	/** The backlog command message type. This message type is used to
	 *  send/receive backlog command messages by the
	 *  {@link gsn.wrappers.backlog.plugins.BackLogStatusPlugin BackLogStatusPlugin}. */
	public static final byte BACKLOG_STATUS_MESSAGE_TYPE = 10;

	/** The CoreStation status message type. This message type is used to
     *  receive CoreStation status messages by the
	 *  {@link gsn.wrappers.backlog.plugins.CoreStationStatusPlugin CoreStationStatusPlugin}. */
	public static final byte CORESTATION_STATUS_MESSAGE_TYPE = 11;

	/** The syslog-ng message type. This message type is used to
     *  receive syslog-ng log messages by the
	 *  {@link gsn.wrappers.backlog.plugins.SyslogNgPlugin SyslogNgPlugin}. */
	public static final byte SYSLOG_NG_MESSAGE_TYPE = 12;

	/** The TOS message type. This message type is used to
	 *  send/receive TOS messages by the
	 *  {@link gsn.wrappers.backlog.plugins.MigMessagePlugin MigMessagePlugin}. */
	public static final byte TOS_MESSAGE_TYPE = 20;
	public static final byte TOS1x_MESSAGE_TYPE = 21;

	/** The binary message type. This message type is used to
     *  receive any binary data by the
	 *  {@link gsn.wrappers.backlog.plugins.BinaryPlugin BinaryPlugin}. */
	public static final byte BINARY_MESSAGE_TYPE = 30;

	/** The Vaisala WXT520 message type. This message type is used to
     *  receive Vaisala WXT520 weather station data.
	 *  {@link gsn.wrappers.backlog.plugins.BinaryBridgePlugin BinaryBridgePlugin}. */
	public static final byte VAISALA_WXT520_MESSAGE_TYPE = 40;

	/** The Schedule message type. This message type is used to
     *  send/receive Schedule data.
	 *  {@link gsn.wrappers.backlog.plugins.SchedulePlugin SchedulePlugin}. */
	public static final byte SCHEDULE_MESSAGE_TYPE = 50;

	/** The GPS message type. This message type is used to
     *  send/receive GPS data.
	 *  {@link gsn.wrappers.backlog.plugins.GPSPlugin GPSPlugin}. */
	public static final byte GPS_MESSAGE_TYPE = 60;
	
	/** The OZ47 message type. This message type is used to
     *  send/receive OZ47 sensor data.
	 *  {@link gsn.wrappers.backlog.plugins.OZ47Plugin OZ47Plugin}. */
	public static final byte OZ47_MESSAGE_TYPE = 70;
	
	/** The ECVQ-EK3 message type. This message type is used to
     *  send/receive sensor data from the sensor evaluation kit.
	 *  {@link gsn.wrappers.backlog.plugins.ECVQEK3Plugin ECVQEK3Plugin}. */
	public static final byte ECVQEK3_MESSAGE_TYPE = 71;
	
	/** PowerManager 
     *  
	 *  {@link gsn.wrappers.backlog.plugins.PowerManagerPlugin PowerManagerPlugin}. */
	public static final byte POWERMANAGER_MESSAGE_TYPE = 72;
	
	
	/* #                                                            #
	 * #                                                            #
	 * ############################################################## */

	
	
	
	
	/** The acknowledge message type. This message type is used to
	 *  acknowledge data messages. */
	public static final byte ACK_MESSAGE_TYPE = 1;
	/** The ping message type. This message type is used to
	 *  ping a deployment, thus, requesting a PING_ACK_MESSAGE_TYPE. */
	public static final byte PING_MESSAGE_TYPE = 2;
	/** The ping acknowledge message type. This message type is used to
	 *  acknowledge a ping request. */
	public static final byte PING_ACK_MESSAGE_TYPE = 3;
	/** The message queue full message type. This message type is used
	 *  to control the message flow. */
	public static final byte MESSAGE_QUEUE_LIMIT_MESSAGE_TYPE = 4;
	/** The message queue ready message type. This message type is used
	 *  to control the message flow. */
	public static final byte MESSAGE_QUEUE_READY_MESSAGE_TYPE = 5;
	

	/** 
	 * The maximum supported payload size (2^32bytes)
	 **/
	public static int MAX_PAYLOAD_SIZE = (int) (Math.pow(2, 16));
	
	private Serializable[] payload = {};
	private byte [] payloadBin = null;
	private long timestamp = 0;
	private byte type = 0;
	
	
	/** 
	 * Class constructor specifying the message type.
	 * 
	 * @param type of the message
	 */
	public BackLogMessage(byte type) {
		this.type = type;
	}
	
	
	/** 
	 * Class constructor specifying the message type and
	 * the timestamp.
	 * 
	 * @param type of the message
	 * @param timestamp in milliseconds
	 */
	public BackLogMessage(byte type, long timestamp) {
		this.type = type;
		this.timestamp = timestamp;
	}
	
	
	/** 
	 * Class constructor specifying the message type, the timestamp
	 * and the payload.
	 * 
	 * @param type of the message
	 * @param timestamp in milliseconds
	 * @param payload of the message.
	 * 
	 * @throws IOException if the payload is too big
	 */
	public BackLogMessage(byte type, long timestamp, Serializable[] payload) throws IOException, NullPointerException {
		if( payload == null )
			throw new NullPointerException("The payload should not be null");
		
		checkPayload(payload);
		
		this.type = type;
		this.timestamp = timestamp;
		this.payload = payload;
		this.payloadBin = null;
	}
	
	
	/** 
	 * Class constructor specifying the message.
	 * 
	 * @param binary message as byte array.
	 * @throws IOException if the message length exceeds MAX_PAYLOAD_SIZE+9
	 */
	public BackLogMessage(byte[] message) throws Exception {
		payloadBin = message;
		ByteBuffer bbuffer = ByteBuffer.wrap(message);
		bbuffer.order(ByteOrder.LITTLE_ENDIAN);
		byte [] arraybuffer = bbuffer.array();
		
		type = bbuffer.get();
		timestamp = bbuffer.getLong();
		
		if (bbuffer.hasRemaining()) {
			int format_len = bbuffer.getInt();
			String format = new String(arraybuffer, bbuffer.position(), format_len);
			bbuffer.position(bbuffer.position()+format_len);
	
			payload = new Serializable [format.length()];
			int payloadIndex = 0;
			CharacterIterator it = new StringCharacterIterator(format);
			for (char ch=it.first(); ch != CharacterIterator.DONE; ch=it.next()) {
				switch (ch) {
				case '0':
					payload[payloadIndex] = null;
					break;
				case 'b':
					payload[payloadIndex] = bbuffer.get();
					break;
				case '?':
					byte bool = bbuffer.get();
					if (bool == 0)
						payload[payloadIndex] = false;
					else if (bool == 1)
						payload[payloadIndex] = true;
					else
						throw new IOException("wrong boolean format");
					break;
				case 'h':
					payload[payloadIndex] = bbuffer.getShort();
					break;
				case 'i':
					payload[payloadIndex] = bbuffer.getInt();
					break;
				case 'q':
					payload[payloadIndex] = bbuffer.getLong();
					break;
				case 'd':
					payload[payloadIndex] = bbuffer.getDouble();
					break;
				case 's':
					int len = bbuffer.getInt();
					payload[payloadIndex] = new String(arraybuffer, bbuffer.position(), len);
					bbuffer.position(bbuffer.position()+len);
					break;
				case 'X':
					int l = bbuffer.getInt();
					byte [] data = new byte [l];
					System.arraycopy(arraybuffer, bbuffer.position(), data, 0, l);
					payload[payloadIndex] = data;
					bbuffer.position(bbuffer.position()+l);
					break;
				default:
					throw new IOException("unrecognized format character received");
				}
				payloadIndex++;
			}
		}
	}
	
	
	/** 
	 * Get the message as byte array.
	 * 
	 * @return the message as byte array
	 */
	public byte[] getBinaryMessage() {
		if (payloadBin == null) {
			ByteBuffer bbuffer = ByteBuffer.allocate(MAX_PAYLOAD_SIZE);
			bbuffer.order(ByteOrder.LITTLE_ENDIAN);
			ByteBuffer outbuffer = ByteBuffer.allocate(MAX_PAYLOAD_SIZE);
			outbuffer.order(ByteOrder.LITTLE_ENDIAN);
	
			String format = "";
	
			for (int i=0; i<payload.length; i++) {
				if (payload[i] == null) {
					format += "0";
				}
				else {
					if (payload[i] instanceof Byte) {
						bbuffer.put((Byte)payload[i]);
						format += "b";
					}
					else if (payload[i] instanceof Boolean) {
						if ((Boolean)payload[i])
							bbuffer.put((byte) 1);
						else
							bbuffer.put((byte) 0);
						format += "?";
					}
					else if (payload[i] instanceof Short) {
						bbuffer.putShort((Short)payload[i]);
						format += "h";
					}
					else if (payload[i] instanceof Integer) {
						bbuffer.putInt((Integer)payload[i]);
						format += "i";
					}
					else if (payload[i] instanceof Long) {
						bbuffer.putLong((Long)payload[i]);
						format += "q";
					}
					else if (payload[i] instanceof Double) {
						bbuffer.putDouble((Double)payload[i]);
						format += "d";
					}
					else if (payload[i] instanceof String) {
						bbuffer.putInt(((String)payload[i]).length());
						try {
							bbuffer.put(((String)payload[i]).getBytes("UTF-8"));
						} catch (UnsupportedEncodingException e) {
							e.printStackTrace();
						}
						format += "s";
					}
					else if (payload[i] instanceof byte[]) {
						bbuffer.putInt(((byte[])payload[i]).length);
						bbuffer.put((byte[])payload[i]);
						format += "X";
					}
					else if (payload[i] instanceof Byte[]) {
						bbuffer.putInt(((Byte[])payload[i]).length);
						byte [] tmp = new byte [((Byte[])payload[i]).length];
						for (int j=0; j<((Byte[])payload[i]).length; j++)
							tmp[j] = ((Byte[])payload[i])[j];
						bbuffer.put(tmp);
						format += "X";
					}
					else
						System.err.print("unsupported type");
				}
			}
	
			outbuffer.put(type);
			outbuffer.putLong(timestamp);
			if (format != "") {
				outbuffer.putInt(format.length());
				try {
					outbuffer.put(format.getBytes("UTF-8"));
				} catch (UnsupportedEncodingException e) {
					e.printStackTrace();
				}
			}
			payloadBin = new byte [outbuffer.position()+bbuffer.position()];
			outbuffer.flip();
			outbuffer.get(payloadBin, 0, outbuffer.limit());
			if (format != "") {
				bbuffer.flip();
				bbuffer.get(payloadBin, outbuffer.limit(), bbuffer.limit());
			}
		}

		return payloadBin;
	}
	
	
	/** 
	 * Get the message type.
	 * 
	 * @return the type of the message
	 */
	public byte getType() {
		return type;
	}
	
	
	/** 
	 * Set the message type.
	 * 
	 * @param type of the message
	 */
	public void setType(byte type) {
		this.type = type;
	}
	
	
	/** 
	 * Get the timestamp of the message.
	 * 
	 * @return the timestamp of the message
	 */
	public long getTimestamp() {
		return timestamp;
	}
	
	
	/** 
	 * Set the timestamp of the message.
	 * 
	 * @param timestamp of the message
	 */
	public void setTimestamp(long timestamp) {
		this.timestamp = timestamp;
	}
	
	
	/** 
	 * Get the payload of the message as byte array.
	 * 
	 * @return the payload as Serializable array
	 */
	public Serializable[] getPayload() {
		return payload;
	}
	
	
	/** 
	 * Set the payload of the message.
	 * 
	 * @param payload of the message. Should not be
	 * 			bigger than MAX_PAYLOAD_SIZE.
	 * 
	 * @throws IOException if the payload length exceeds MAX_PAYLOAD_SIZE
	 */
	public void setPayload(Serializable[] payload) throws IOException {
		checkPayload(payload);
		
		this.payload = payload;
	}
	
	
	/** 
	 * Get the size of the message.
	 * 
	 * @return the the size of the message
	 * 
	 * @throws IOException if the payload length exceeds MAX_PAYLOAD_SIZE
	 */
	public int getSize() throws IOException {
		if (payloadBin == null)
			return checkPayload(payload);
		else
			return payloadBin.length;
	}
	
	
	private int checkPayload(Serializable[] payload) throws IOException {
		int length = 2;
		for (int i=0; i<payload.length; i++) {
			if (payload[i] == null)
				length += 1;
			else if (payload[i] instanceof Byte)
				length += 2;
			else if (payload[i] instanceof Boolean)
				length += 2;
			else if (payload[i] instanceof Short)
				length += 3;
			else if (payload[i] instanceof Integer)
				length += 5;
			else if (payload[i] instanceof Long)
				length += 9;
			else if (payload[i] instanceof Double)
				length += 9;
			else if (payload[i] instanceof String)
				length += ((String)payload[i]).length()+3;
			else if (payload[i] instanceof byte[])
				length += ((byte[])payload[i]).length+3;
			else if (payload[i] instanceof Byte[])
				length += ((Byte[])payload[i]).length+3;
			else
				throw new IOException("unsupported type in payload (index=" + i + ", type=" + payload[i].getClass().getName() + ").");
		}

		if( length > MAX_PAYLOAD_SIZE )
			throw new IOException("The payload exceeds the maximum size of " + MAX_PAYLOAD_SIZE + "bytes.");
		
		return length;
	}
}